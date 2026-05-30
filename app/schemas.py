from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field
FieldType = Literal['text','textarea','select','multi_select','number','slider','boolean','file','date','json']
class CustomizationField(BaseModel):
    key: str
    label: str
    type: FieldType = 'text'
    options: list[str] | None = None
    default: Any | None = None
    required: bool = False
    help: str = ''
    affects: list[str] = Field(default_factory=list)
    min: int | None = None
    max: int | None = None
class ProjectSpec(BaseModel):
    slug: str
    name: str
    domain: str
    target_user: str
    core_job: str
    deep_features: list[str] = Field(default_factory=list)
    input_schema: list[CustomizationField] = Field(default_factory=list)
    customization_schema: list[CustomizationField] = Field(default_factory=list)
    workflow_steps: list[str] = Field(default_factory=list)
    ui_panels: list[str] = Field(default_factory=list)
    output_formats: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    recommended_models: dict[str, str] = Field(default_factory=dict)
    suite: str = 'General Automation Suite'
    implementation_status: str = 'configured'
    analysis_modules: list[str] = Field(default_factory=list)
    output_sections: list[str] = Field(default_factory=list)
    field_validations: list[dict[str, Any]] = Field(default_factory=list)
    scorecards: list[str] = Field(default_factory=list)
    automation_hooks: list[dict[str, Any]] = Field(default_factory=list)
    ux_profile: dict[str, Any] = Field(default_factory=dict)
    final_gui_status: dict[str, Any] = Field(default_factory=dict)
class ProviderConfig(BaseModel):
    name: str
    provider_type: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    endpoint: str | None = None
    deployment: str | None = None
    enabled: bool = True
    is_local: bool = False
    default_temperature: float = 0.2
    max_tokens: int = 4000
class RunRequest(BaseModel):
    project_slug: str
    provider_name: str
    model: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    customization: dict[str, Any] = Field(default_factory=dict)
    uploaded_file_ids: list[int] = Field(default_factory=list)
    output_style: str = 'structured markdown report'
    temperature: float | None = None
    max_tokens: int | None = None
class RunResponse(BaseModel):
    job_id: int
    status: str
    output: str
    usage: dict[str, Any] = Field(default_factory=dict)
