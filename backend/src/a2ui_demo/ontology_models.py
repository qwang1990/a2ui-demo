from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AipInputSpec(BaseModel):
    """Declared inputs for starting an AIP flow (attribute keys + required)."""

    model_config = ConfigDict(populate_by_name=True)

    attribute_api_name: str = Field(alias="attributeApiName")
    required: bool = True
    description: str | None = None


class AipLogicMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    entry: str
    inputs: list[AipInputSpec] = Field(default_factory=list)


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


class MockUserFlagsImplementation(BaseModel):
    """
    Logic backed by HTTP GET: URL 由 requestPathTemplate 与 attrs 中的占位符拼出，
    占位符名须与 objectTypes 中某属性的 apiName（camelCase）一致。
    响应 JSON 中取 flagKey 布尔值作为本 logic 的真值。
    """

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["mock_user_flags"] = "mock_user_flags"
    flag_key: str = Field(alias="flagKey")
    request_path_template: str = Field(
        default="/api/mock-ontology/user/{idNumber}",
        alias="requestPathTemplate",
        description="Relative to platform base URL; {attrApiName} filled from FlowState.attrs.",
    )


class LogicDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_name: str = Field(alias="apiName")
    display_name: str | None = Field(None, alias="displayName")
    description: str | None = None
    implementation: MockUserFlagsImplementation


class ActionDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_name: str = Field(alias="apiName")
    display_name: str | None = Field(None, alias="displayName")
    description: str | None = None
    implementation_key: str = Field(alias="implementationKey")


class OntologyNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["logic", "collect", "action", "terminal"]
    edges: LogicEdges | None = None
    next: str | None = None
    object_type_api_name: str | None = Field(None, alias="objectTypeApiName")
    property_api_names: list[str] | None = Field(None, alias="propertyApiNames")
    title: str | None = None
    outcome: Literal["approved", "denied"] | None = None
    message: str | None = None
    logic_ref: str | None = Field(None, alias="logicRef")
    action_ref: str | None = Field(None, alias="actionRef")


class OntologySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ontology_version: int | str = Field(1, alias="ontologyVersion")
    logic_definitions: list[LogicDefinition] = Field(default_factory=list, alias="logicDefinitions")
    action_definitions: list[ActionDefinition] = Field(default_factory=list, alias="actionDefinitions")
    aip_logic: AipLogicMeta
    object_types: list[ObjectTypeDef] = Field(alias="objectTypes")
    nodes: list[OntologyNode]

    def node_by_id(self) -> dict[str, OntologyNode]:
        return {n.id: n for n in self.nodes}

    def logic_by_api_name(self) -> dict[str, LogicDefinition]:
        return {d.api_name: d for d in self.logic_definitions}

    def action_by_api_name(self) -> dict[str, ActionDefinition]:
        return {d.api_name: d for d in self.action_definitions}

    def property_labels(self) -> dict[str, str]:
        """Map property apiName -> display label for forms."""
        out: dict[str, str] = {}
        for ot in self.object_types:
            for p in ot.properties:
                out[p.api_name] = p.display_name or p.api_name
        return out

    def property_api_names_ordered(self) -> list[str]:
        """Declare order of properties across object types (ontology JSON order)."""
        out: list[str] = []
        for ot in self.object_types:
            for p in ot.properties:
                if p.api_name not in out:
                    out.append(p.api_name)
        return out

    def property_names_for_object_type(self, api_name: str | None) -> list[str]:
        """Ordered property apiNames for a single object type (empty if unknown)."""
        if not api_name:
            return []
        for ot in self.object_types:
            if ot.api_name == api_name:
                return [p.api_name for p in ot.properties]
        return []
