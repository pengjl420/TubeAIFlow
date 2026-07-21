from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.render import MotionPreset


LibraryRole = Literal["semantic", "themed_fallback", "landscape_fallback"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class AssetImportRequest(BaseModel):
    directory: str = Field(min_length=1)
    library_role: LibraryRole = "semantic"
    fallback_category: str = Field(default="", max_length=60)
    mood: str = Field(default="", max_length=60)

    @model_validator(mode="after")
    def validate_fallback_category(self):
        if self.library_role == "themed_fallback" and not self.fallback_category.strip():
            raise ValueError("主题兜底素材必须填写兜底类别")
        self.fallback_category = self.fallback_category.strip()
        self.mood = self.mood.strip()
        return self


class AssetUpdateRequest(BaseModel):
    library_role: LibraryRole
    fallback_category: str = Field(default="", max_length=60)
    mood: str = Field(default="", max_length=60)
    review_status: ReviewStatus = "approved"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_fallback_category(self):
        if self.library_role == "themed_fallback" and not self.fallback_category.strip():
            raise ValueError("主题兜底素材必须填写兜底类别")
        self.fallback_category = self.fallback_category.strip()
        self.mood = self.mood.strip()
        return self


class AssetBatchDeleteRequest(BaseModel):
    media_ids: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def normalize_media_ids(self):
        self.media_ids = list(dict.fromkeys(media_id.strip() for media_id in self.media_ids if media_id.strip()))
        if not self.media_ids:
            raise ValueError("请至少选择一个要删除的素材")
        return self


class SceneAssignmentRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    manual_override: bool = False
    append: bool = False
    trim_start_ms: int = Field(default=0, ge=0)
    trim_end_ms: int | None = Field(default=None, gt=0)
    playback_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    display_duration_ms: int | None = Field(default=None, ge=500, le=60000)
    render_mode: Literal["auto", "ffmpeg"] = "auto"
    motion_type: MotionPreset = "auto"
    zoom_start: float = Field(default=1.0, ge=1.0, le=1.2)
    zoom_end: float = Field(default=1.06, ge=1.0, le=1.2)
    pan_direction: Literal["center", "left", "right", "up", "down"] = "center"
    crop_anchor: Literal["center", "left", "right", "top", "bottom"] = "center"
    transition: str = Field(default="cut", min_length=1, max_length=30)


class SceneAssignmentReorderRequest(BaseModel):
    assignment_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_assignment_ids(self):
        if len(set(self.assignment_ids)) != len(self.assignment_ids):
            raise ValueError("镜头轨道中不能包含重复指派")
        return self


class SceneAssignmentRenderUpdate(BaseModel):
    render_mode: Literal["auto", "ffmpeg"] = "auto"
    motion_type: MotionPreset
    zoom_start: float = Field(default=1.0, ge=1.0, le=1.2)
    zoom_end: float = Field(default=1.06, ge=1.0, le=1.2)
    pan_direction: Literal["center", "left", "right", "up", "down"] = "center"
    crop_anchor: Literal["center", "left", "right", "top", "bottom"] = "center"


class RemoteMediaCandidate(BaseModel):
    provider: str
    asset_id: str
    media_type: str = "video"
    page_url: str
    preview_url: str | None = None
    download_url: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    author: str = ""
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    query: str = ""
