"""Un strat subțire peste Starlette.

Face trei lucruri, ca să nu le repetăm în fiecare endpoint:
  1. validează parametrii și corpul cererii cu pydantic;
  2. întoarce erorile în română, în formatul {"detail": "..."};
  3. generează documentația OpenAPI, vizibilă în browser la /docs (unde puteți și testa endpoint-urile).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route


class EroareAPI(Exception):
    """Ridicați-o dintr-un endpoint pentru un răspuns de eroare clar: raise EroareAPI(404, 'Nu există.')"""

    def __init__(self, status: int, detaliu: str, **extra: Any):
        super().__init__(detaliu)
        self.status, self.detaliu, self.extra = status, detaliu, extra


def _json_implicit(o: Any):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):          # tipuri numpy (int64, float32...)
        return o.item()
    if hasattr(o, "tolist"):        # vectori numpy
        return o.tolist()
    raise TypeError(f"Nu pot transforma în JSON: {type(o).__name__}")


class RaspunsJSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                          default=_json_implicit).encode("utf-8")


@dataclass
class _Meta:
    metoda: str
    cale: str
    query: Optional[type]
    corp: Optional[type]
    formular: Optional[dict]
    tag: str
    rezumat: str
    descriere: str


class Api:
    def __init__(self, titlu: str, versiune: str, descriere: str):
        self.titlu, self.versiune, self.descriere = titlu, versiune, descriere
        self.rute: list[Route] = []
        self._meta: list[_Meta] = []

    def ruta(self, metoda: str, cale: str, *, query: Optional[type] = None, corp: Optional[type] = None,
             formular: Optional[dict] = None, tag: str = "", rezumat: str = "", descriere: str = ""):
        """Înregistrează un endpoint. Funcția primește request-ul plus q=… (query) și/sau corp=… (JSON)."""

        def decor(fn: Callable[..., Awaitable[Any]]):
            async def handler(request: Request) -> Response:
                try:
                    kwargs: dict[str, Any] = {}
                    if query is not None:
                        kwargs["q"] = query.model_validate(dict(request.query_params))
                    if corp is not None:
                        try:
                            brut = await request.json()
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            raise EroareAPI(400, "Corpul cererii trebuie să fie JSON valid.")
                        kwargs["corp"] = corp.model_validate(brut)
                    rezultat = await fn(request, **kwargs)
                    return rezultat if isinstance(rezultat, Response) else RaspunsJSON(rezultat)
                except EroareAPI as e:
                    return RaspunsJSON({"detail": e.detaliu, **e.extra}, status_code=e.status)
                except ValidationError as e:
                    erori = [{"camp": ".".join(str(x) for x in er["loc"]) or "(corp)", "problema": er["msg"]}
                             for er in e.errors()]
                    return RaspunsJSON({"detail": "Date invalide în cerere.", "erori": erori}, status_code=422)

            handler.__name__ = fn.__name__
            self.rute.append(Route(cale, handler, methods=[metoda]))
            self._meta.append(_Meta(metoda, cale, query, corp, formular, tag, rezumat or fn.__name__,
                                    descriere or (fn.__doc__ or "").strip()))
            return fn

        return decor

    # ---------- documentație ----------

    def openapi(self) -> dict:
        componente: dict[str, Any] = {}
        cai: dict[str, dict] = {}
        sablon = "#/components/schemas/{model}"
        for m in self._meta:
            op: dict[str, Any] = {
                "summary": m.rezumat,
                "description": m.descriere,
                "tags": [m.tag] if m.tag else [],
                "responses": {"200": {"description": "OK"}, "422": {"description": "Date invalide"}},
            }
            parametri = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                         for n in re.findall(r"{(\w+)}", m.cale)]
            if m.query is not None:
                schema = m.query.model_json_schema(ref_template=sablon)
                componente.update(schema.pop("$defs", {}))
                obligatorii = set(schema.get("required", []))
                for nume, prop in schema.get("properties", {}).items():
                    p = {"name": nume, "in": "query", "required": nume in obligatorii, "schema": prop}
                    if "description" in prop:
                        p["description"] = prop["description"]
                    parametri.append(p)
            if parametri:
                op["parameters"] = parametri
            if m.corp is not None:
                schema = m.corp.model_json_schema(ref_template=sablon)
                componente.update(schema.pop("$defs", {}))
                componente[m.corp.__name__] = schema
                op["requestBody"] = {"required": True, "content": {"application/json": {
                    "schema": {"$ref": sablon.format(model=m.corp.__name__)}}}}
            if m.formular is not None:
                op["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": m.formular}}}
            cai.setdefault(m.cale, {})[m.metoda.lower()] = op
        return {
            "openapi": "3.1.0",
            "info": {"title": self.titlu, "version": self.versiune, "description": self.descriere},
            "paths": cai,
            "components": {"schemas": componente},
        }

    def rute_documentatie(self) -> list[Route]:
        async def specificatie(_: Request) -> Response:
            return RaspunsJSON(self.openapi())

        async def pagina(_: Request) -> Response:
            return HTMLResponse(_PAGINA_DOCS.replace("__TITLU__", self.titlu))

        return [Route("/openapi.json", specificatie, methods=["GET"]),
                Route("/docs", pagina, methods=["GET"])]


_PAGINA_DOCS = """<!doctype html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLU__ – documentație</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>body{margin:0}</style></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
  window.ui = SwaggerUIBundle({ url: "/openapi.json", dom_id: "#swagger-ui", deepLinking: true,
    tryItOutEnabled: true, defaultModelsExpandDepth: 0 });
</script>
<noscript>Documentația are nevoie de JavaScript. Specificația brută: <a href="/openapi.json">/openapi.json</a></noscript>
</body></html>"""
