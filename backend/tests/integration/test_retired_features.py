from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.models.narration import Segment
from app.models.project import Project
from app.models.storyboard import SubtitleCue
from app.models.task import TaskRun
from app.providers.llm import build_storyboard_llm
from app.services.narration import srt_service, subtitle_service
from app.services.tasks import task_worker


def test_cloud_llm_ignores_legacy_local_strategy(tmp_path):
    settings = Settings(workspace_dir=tmp_path, deepseek_api_key='test-key',
                        storyboard_llm_strategy='local', local_llm_base_url='http://localhost:1',
                        storyboard_llm_cache_enabled=False)
    with patch('app.providers.llm.get_settings', return_value=settings):
        assert build_storyboard_llm().name == 'llm.deepseek'
    assert 'local_llm_base_url' not in settings.model_dump()
    with patch('app.providers.llm.get_settings', return_value=Settings()):
        with pytest.raises(ValueError, match='DeepSeek'):
            build_storyboard_llm()


def test_basic_srt_uses_segment_audio_duration_without_asr(tmp_path):
    settings = Settings(workspace_dir=tmp_path)
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(id='basic', name='Basic', output_dir=str(tmp_path))
        segment = Segment(id='seg1', project_id='basic', segment_id='0001', segment_index=1,
                          text='原稿第一句。这是原稿第二句。', duration=12.0, start_time=0, end_time=12)
        session.add(project)
        session.add(segment)
        session.commit()
        with patch.object(srt_service, 'get_settings', return_value=settings):
            path = srt_service.create_full_srt(project, [segment], session=session)
        cues = list(session.exec(select(SubtitleCue).order_by(SubtitleCue.start_ms)).all())
        parsed = subtitle_service.parse_srt(path.read_text(encoding='utf-8'))
        assert parsed[0]['start_ms'] == cues[0].start_ms == 0
        assert parsed[-1]['end_ms'] == cues[-1].end_ms == 12000
        assert ''.join(cue.text for cue in cues) == segment.text
    engine.dispose()


@pytest.mark.parametrize('status', ['queued', 'running', 'paused'])
def test_retired_preview_jobs_never_restart(status):
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Project(id='p', name='P', status='review_required'))
        task = TaskRun(id='old-preview', project_id='p', workflow='scene_preview_render',
                       job_type='scene_preview_render', status=status, current_stage='render',
                       queue_sequence=1)
        session.add(task)
        session.commit()
        task_worker.recover_interrupted_tasks(session)
        session.refresh(task)
        assert task.status == 'cancelled'
        assert task.finished_at
        assert session.get(Project, 'p').status == 'review_required'
    engine.dispose()


def test_removed_endpoints_are_absent():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert not any('/models/llm' in path or '/tools/local-video-merge' in path for path in paths)
    assert not any(path.endswith('/preview') or path.endswith('/subtitles/alignment') for path in paths)
    assert '/projects/{project_id}/render/scenes/{scene_id}' not in paths
    assert '/api/projects/{project_id}/render/scenes/{scene_id}' not in paths
