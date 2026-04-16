from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    allow_incomplete_graph: bool = Field(
        False,
        alias="allowIncompleteGraph",
        description="允许 collect/action 无 next（编排草稿）；编译时挂到隐式结束节点。",
    )


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
    constraints: "PropertyConstraints | None" = None


class PropertyConstraints(BaseModel):
    """Validation constraints used by both frontend and runtime."""

    model_config = ConfigDict(populate_by_name=True)

    required: bool | None = None
    message: str | None = None
    min_length: int | None = Field(None, alias="minLength")
    max_length: int | None = Field(None, alias="maxLength")
    pattern: str | None = None
    format: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum_values: list[str] | None = Field(None, alias="enumValues")

    @model_validator(mode="after")
    def _validate_range(self) -> "PropertyConstraints":
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("minLength cannot be greater than maxLength")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot be greater than maximum")
        return self


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


class LogicParameterBinding(BaseModel):
    """将 ``attrs`` 中的值映射到 logic HTTP 路径模板 ``{templateKey}`` 占位符。"""

    model_config = ConfigDict(populate_by_name=True)

    from_attr: str = Field(alias="fromAttr", description="从 attrs 读取的键（通常来自上一节点输出）")
    template_key: str = Field(alias="templateKey", description="与 requestPathTemplate 中 {占位符} 同名")


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
    response_to_attrs: list[str] | None = Field(
        None,
        alias="responseToAttrs",
        description="可选；无 expression 时由 logic HTTP 响应按列名合并进 attrs。",
    )
    expression: str | None = None
    logic_parameter_bindings: list[LogicParameterBinding] | None = Field(
        None,
        alias="logicParameterBindings",
        description="可选；logic 节点 HTTP 路径占位符与 attrs 键的显式映射。",
    )


class OntologySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ontology_version: int | str = Field(1, alias="ontologyVersion")
    logic_definitions: list[LogicDefinition] = Field(default_factory=list, alias="logicDefinitions")
    action_definitions: list[ActionDefinition] = Field(default_factory=list, alias="actionDefinitions")
    aip_logic: AipLogicMeta
    object_types: list[ObjectTypeDef] = Field(alias="objectTypes")
    nodes: list[OntologyNode] = Field(default_factory=list)
    aip_logic_graph: "AipLogicGraph | None" = Field(default=None, alias="aip_logic_graph")

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

    def property_constraints(self) -> dict[str, PropertyConstraints]:
        out: dict[str, PropertyConstraints] = {}
        for ot in self.object_types:
            for p in ot.properties:
                if p.constraints:
                    out[p.api_name] = p.constraints
        return out


class AipGraphPosition(BaseModel):
    x: float = 0
    y: float = 0


class AipGraphNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["start", "end", "logic", "action", "collect", "terminal"]
    title: str | None = None
    object_type_api_name: str | None = Field(None, alias="objectTypeApiName")
    property_api_names: list[str] | None = Field(None, alias="propertyApiNames")
    outcome: Literal["approved", "denied"] | None = None
    message: str | None = None
    logic_ref: str | None = Field(None, alias="logicRef")
    action_ref: str | None = Field(None, alias="actionRef")
    input_property_api_names: list[str] | None = Field(None, alias="inputPropertyApiNames")
    response_to_attrs: list[str] | None = Field(None, alias="responseToAttrs")
    expression: str | None = None
    position: AipGraphPosition = Field(default_factory=AipGraphPosition)
    logic_parameter_bindings: list[LogicParameterBinding] | None = Field(None, alias="logicParameterBindings")


class AipGraphEdge(BaseModel):
    source: str
    target: str
    condition: Literal["next", "true", "false"] = "next"


class AipLogicGraph(BaseModel):
    version: int = 1
    nodes: list[AipGraphNode] = Field(default_factory=list)
    edges: list[AipGraphEdge] = Field(default_factory=list)

    def to_ontology_nodes(self) -> list[OntologyNode]:
        edge_map: dict[str, list[AipGraphEdge]] = {}
        for e in self.edges:
            edge_map.setdefault(e.source, []).append(e)
        out: list[OntologyNode] = []
        for n in self.nodes:
            edges = edge_map.get(n.id, [])
            if n.kind == "logic":
                true_target = next((e.target for e in edges if e.condition == "true"), None)
                false_target = next((e.target for e in edges if e.condition == "false"), None)
                out.append(
                    OntologyNode(
                        id=n.id,
                        kind="logic",
                        edges=LogicEdges(true=true_target, false=false_target),
                        logicRef=n.logic_ref,
                        title=n.title,
                        expression=n.expression,
                        responseToAttrs=n.response_to_attrs,
                        logicParameterBindings=n.logic_parameter_bindings,
                    )
                )
            elif n.kind in ("collect", "action", "start"):
                nxt = next((e.target for e in edges if e.condition == "next"), None)
                kind: Literal["collect", "action"] = "collect" if n.kind == "start" else n.kind
                props = n.property_api_names if n.kind != "start" else (n.input_property_api_names or n.property_api_names)
                out.append(
                    OntologyNode(
                        id=n.id,
                        kind=kind,
                        next=nxt,
                        objectTypeApiName=n.object_type_api_name,
                        propertyApiNames=props,
                        title=n.title,
                        logicRef=n.logic_ref,
                        actionRef=n.action_ref,
                    )
                )
            else:
                outcome = n.outcome
                if n.kind == "end" and outcome is None:
                    outcome = "approved"
                out.append(
                    OntologyNode(
                        id=n.id,
                        kind="terminal",
                        title=n.title,
                        outcome=outcome,
                        message=n.message,
                    )
                )
        return out
