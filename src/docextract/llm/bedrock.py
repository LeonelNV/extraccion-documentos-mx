"""Cliente de Amazon Bedrock para los extractores B y C1.

Una llamada = un documento. Se usa la API Converse con **salida forzada por herramienta**:
el modelo solo puede responder llamando a ``registrar_campos``, cuyo esquema JSON lista los
campos del tipo de documento. La respuesta es un dict que después valida pydantic
(:mod:`docextract.llm.prompts`).

Decisiones:

* **Solo modelos que corren en la región** (us-east-1). Los perfiles de inferencia entre
  regiones (``us.``) reparten las llamadas a otras regiones, y una política de la
  organización de la cuenta niega invocar fuera de us-east-1.
* ``maxTokens`` explícito y temperatura 0: sin ``maxTokens`` Bedrock reserva el máximo del
  modelo contra la cuota.
* Reintentos adaptativos de botocore para ``ThrottlingException`` y errores 5xx; los
  errores de validación o de permisos no se reintentan y detienen la corrida. Si el modelo
  genera una llamada a la herramienta mal formada (``ModelErrorException``), se reintenta
  una vez y después la respuesta cuenta como inválida.
* **Costo** = tokens que reporta Bedrock x precio de :data:`PRECIOS` (Price List API, con
  fecha y fuente en ``precios_bedrock.json``).
* **Tope de gasto** (:class:`Presupuesto`): antes de cada llamada se suma el peor caso
  (entrada estimada + ``maxTokens`` de salida); si pasaría el tope, no se llama.
* **Caché** (:class:`LlmCache`), **solo para datos sintéticos**: guarda la respuesta por
  hash de la petición para que repetir la evaluación no cueste.

Privacidad: el texto o la imagen del documento viajan a Bedrock. En este repo solo se
envían documentos sintéticos (ver ``eval/evaluate_llm.py``).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = [
    "REGION",
    "BedrockClient",
    "LlmCache",
    "ModeloBedrock",
    "Presupuesto",
    "PresupuestoAgotadoError",
    "Respuesta",
    "modelo",
    "precios",
]

REGION = "us-east-1"
HERRAMIENTA = "registrar_campos"
REINTENTOS_ERROR_DEL_MODELO = 1
"""``ModelErrorException``: el modelo generó una llamada a la herramienta mal formada (pasa
con Nova). Se reintenta una vez; si vuelve a fallar, la respuesta cuenta como inválida."""


@dataclass(frozen=True)
class ModeloBedrock:
    id: str
    nombre: str
    vision: bool
    entrada_1k: float
    """USD por 1,000 tokens de entrada."""
    salida_1k: float

    def costo(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens / 1000 * self.entrada_1k + output_tokens / 1000 * self.salida_1k


@cache
def precios() -> dict[str, Any]:
    """La tabla de precios con su fuente y fecha."""
    texto = resources.files("docextract.llm").joinpath("precios_bedrock.json").read_text("utf-8")
    return json.loads(texto)


def modelo(model_id: str) -> ModeloBedrock:
    datos = precios()["modelos"].get(model_id)
    if datos is None:
        conocidos = ", ".join(precios()["modelos"])
        raise ValueError(f"Modelo sin precio en precios_bedrock.json: {model_id}. Hay: {conocidos}")
    return ModeloBedrock(id=model_id, **datos)


# ---------------------------------------------------------------------------
# Tope de gasto
# ---------------------------------------------------------------------------
class PresupuestoAgotadoError(RuntimeError):
    """La siguiente llamada podría pasar el tope de gasto: no se hizo."""


class Presupuesto:
    """Gasto acumulado con un tope. Seguro entre hilos.

    ``reservar`` aparta el peor caso antes de llamar y ``liquidar`` lo reemplaza por el
    costo real, así varias llamadas en paralelo no pasan el tope.
    """

    def __init__(self, limite_usd: float, gastado_usd: float = 0.0) -> None:
        self.limite_usd = limite_usd
        self.gastado_usd = gastado_usd
        self._reservado = 0.0
        self._lock = threading.Lock()

    def reservar(self, maximo_usd: float) -> None:
        with self._lock:
            if self.gastado_usd + self._reservado + maximo_usd > self.limite_usd:
                raise PresupuestoAgotadoError(
                    f"Tope de ${self.limite_usd:.2f} USD: gastado ${self.gastado_usd:.4f}; "
                    f"la siguiente llamada podría costar hasta ${maximo_usd:.4f}."
                )
            self._reservado += maximo_usd

    def liquidar(self, reservado_usd: float, real_usd: float) -> None:
        with self._lock:
            self._reservado -= reservado_usd
            self.gastado_usd += real_usd


# ---------------------------------------------------------------------------
# Respuesta y caché
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Respuesta:
    datos: dict[str, Any] | None
    """Lo que el modelo pasó a la herramienta; ``None`` si no la llamó."""
    input_tokens: int
    output_tokens: int
    costo_usd: float
    latencia_ms: float
    stop_reason: str
    texto: str = ""
    """Texto libre que el modelo haya escrito además de (o en vez de) llamar la herramienta."""
    de_cache: bool = field(default=False, compare=False)


class LlmCache:
    """Respuestas por hash de la petición (modelo + prompt + documento).

    Solo para datos sintéticos: guarda en disco lo que el modelo leyó del documento.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, key: str) -> Path:
        return self.folder / key[:2] / f"{key}.json"

    def get(self, key: str) -> Respuesta | None:
        path = self._path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Respuesta(**data, de_cache=True)

    def put(self, key: str, respuesta: Respuesta) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(respuesta)
        data.pop("de_cache")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def request_key(request: dict[str, Any]) -> str:
    """Hash estable de la petición; las imágenes entran por su propio hash."""

    def default(value: Any) -> Any:
        if isinstance(value, bytes):
            return {"sha256": hashlib.sha256(value).hexdigest()}
        raise TypeError(type(value))

    texto = json.dumps(request, sort_keys=True, ensure_ascii=False, default=default)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
def _default_client() -> Any:
    import boto3
    from botocore.config import Config

    config = Config(
        retries={"max_attempts": 6, "mode": "adaptive"},
        read_timeout=120,
        connect_timeout=10,
    )
    return boto3.client("bedrock-runtime", region_name=REGION, config=config)


def estimar_tokens_entrada(content: list[dict[str, Any]], system: str, schema: dict) -> int:
    """Cota superior aproximada, solo para reservar presupuesto (~3 caracteres por token y
    hasta 5,000 tokens por imagen)."""
    caracteres = len(system) + len(json.dumps(schema, ensure_ascii=False))
    imagenes = 0
    for block in content:
        caracteres += len(block.get("text", ""))
        imagenes += "image" in block
    return caracteres // 3 + 5000 * imagenes + 200


class BedrockClient:
    def __init__(
        self,
        *,
        client: Any = None,
        presupuesto: Presupuesto | None = None,
        cache: LlmCache | None = None,
    ) -> None:
        self._client = client
        self._lock = threading.Lock()
        self.presupuesto = presupuesto
        self.cache = cache

    @property
    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = _default_client()
            return self._client

    def extraer(
        self,
        model: ModeloBedrock,
        *,
        system: str,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
    ) -> Respuesta:
        """Una llamada a Converse con la herramienta ``registrar_campos`` forzada."""
        request = {
            "modelId": model.id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": HERRAMIENTA,
                            "description": "Registra los campos leídos del documento.",
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": HERRAMIENTA}},
            },
        }
        key = request_key(request)
        if self.cache is not None and (guardada := self.cache.get(key)) is not None:
            return guardada

        response = None
        for intento in range(1 + REINTENTOS_ERROR_DEL_MODELO):
            reserva = 0.0
            if self.presupuesto is not None:
                reserva = model.costo(estimar_tokens_entrada(content, system, schema), max_tokens)
                self.presupuesto.reservar(reserva)
            start = time.perf_counter()
            try:
                response = self.client.converse(**request)
            except Exception as error:
                if _codigo(error) != "ModelErrorException":
                    if self.presupuesto is not None:
                        # Una llamada rechazada (permisos, validación) no se cobra.
                        self.presupuesto.liquidar(reserva, 0.0)
                    raise
                # El modelo generó una llamada a la herramienta mal formada. Bedrock no
                # reporta tokens: se cuenta el peor caso, por prudencia.
                if self.presupuesto is not None:
                    self.presupuesto.liquidar(reserva, reserva)
                if intento == REINTENTOS_ERROR_DEL_MODELO:
                    # No se guarda en la caché: otra corrida lo vuelve a intentar.
                    return Respuesta(
                        datos=None,
                        input_tokens=0,
                        output_tokens=0,
                        costo_usd=model.costo(
                            estimar_tokens_entrada(content, system, schema), max_tokens
                        ),
                        latencia_ms=(time.perf_counter() - start) * 1000,
                        stop_reason="ModelErrorException",
                    )
                continue
            break
        assert response is not None
        latencia = (time.perf_counter() - start) * 1000
        usage = response.get("usage", {})
        input_tokens = int(usage.get("inputTokens", 0))
        output_tokens = int(usage.get("outputTokens", 0))
        costo = model.costo(input_tokens, output_tokens)
        if self.presupuesto is not None:
            self.presupuesto.liquidar(reserva, costo)

        datos, textos = None, []
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block and block["toolUse"].get("name") == HERRAMIENTA:
                datos = block["toolUse"].get("input")
            elif "text" in block:
                textos.append(block["text"])
        if datos is None:
            datos = _json_en_texto("\n".join(textos))
        respuesta = Respuesta(
            datos=datos if isinstance(datos, dict) else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            costo_usd=costo,
            latencia_ms=latencia,
            stop_reason=str(response.get("stopReason", "")),
            texto="\n".join(textos),
        )
        if self.cache is not None:
            self.cache.put(key, respuesta)
        return respuesta


def _codigo(error: Exception) -> str | None:
    """El código de error de botocore (``ClientError``), si lo es."""
    response = getattr(error, "response", None)
    return response.get("Error", {}).get("Code") if isinstance(response, dict) else None


def _json_en_texto(texto: str) -> dict[str, Any] | None:
    """Respaldo para un modelo que escribe el JSON como texto en vez de usar la herramienta.

    >>> _json_en_texto('Aquí está: {"curp": "X"} listo')
    {'curp': 'X'}
    >>> _json_en_texto("sin json") is None
    True
    """
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        data = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
