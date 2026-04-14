from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AipLogicMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    entry: str


PropertyType = Literal["string", "boolean", "integer", "double", "timestamp", "byte"]
FieldSource = Literal["user_input", "ontology_api"]


class ObjectProperty(BaseModel):
    """Palantir Foundry–style property on an object type."""

    model_config = ConfigDict(populate_by_name=True)

    api_name: str = Field(alias="apiName")
    type: PropertyType = "string"
    display_name: str | None = Field(None, alias="displayName")
    description: str | None = None
    required: bool = False
    field_source: FieldSource = Field("user_input", alias="fieldSource")


class ObjectTypeDef(BaseModel):
    """Palantir Foundry–style object type."""

    model_config = ConfigDict(populate_by_name=True)

    api_name: str = Field(alias="apiName")
    display_name: str | None = Field(None, alias="displayName")
    description: str | None = None
    properties: list[ObjectProperty] = Field(default_factory=list)


class LogicEdges(BaseModel):
    true: str | None = None
    false: str | None = None


class OntologyNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["logic", "collect", "action", "terminal"]
    predicate: str | None = None
    edges: LogicEdges | None = None
    next: str | None = None
    object_type_api_name: str | None = Field(None, alias="objectTypeApiName")
    property_api_names: list[str] | None = Field(None, alias="propertyApiNames")
    action_name: str | None = None
    title: str | None = None
    outcome: Literal["approved", "denied"] | None = None
    message: str | None = None


class OntologySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    aip_logic: AipLogicMeta
    object_types: list[ObjectTypeDef] = Field(alias="objectTypes")
    nodes: list[OntologyNode]

    def node_by_id(self) -> dict[str, OntologyNode]:
        return {n.id: n for n in self.nodes}

    def property_labels(self) -> dict[str, str]:
        """Map property apiName -> display label for forms."""
        out: dict[str, str] = {}
        for ot in self.object_types:
            for p in ot.properties:
                out[p.api_name] = p.display_name or p.api_name
        return out
