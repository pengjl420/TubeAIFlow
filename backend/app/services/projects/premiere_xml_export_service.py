from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from app.config import get_settings
from app.infrastructure.project_layout import get_final_premiere_xml_path
from app.models.project import Project


FPS = 30
XMEML_VERSION = "5"


def convert_fcpxml_for_premiere(project: Project, fcpxml_path: Path) -> dict:
    """Convert the app's FCPXML timeline to Premiere-compatible FCP 7 XML."""
    source_path = fcpxml_path.expanduser().resolve()
    source_root = ET.parse(source_path).getroot()
    if source_root.tag != "fcpxml":
        raise ValueError("Expected an FCPXML document")

    source_sequence = source_root.find("./library/event/project/sequence")
    if source_sequence is None:
        raise ValueError("FCPXML has no project sequence")

    resources = {
        node.attrib["id"]: node
        for node in source_root.findall("./resources/asset")
        if node.attrib.get("id")
    }
    project_name = (
        source_root.find("./library/event/project").attrib.get("name", project.name)
        if source_root.find("./library/event/project") is not None
        else project.name
    )
    total_frames = max(1, _frames(source_sequence.attrib.get("duration", "0s")))

    root = ET.Element("xmeml", {"version": XMEML_VERSION})
    project_node = ET.SubElement(root, "project")
    ET.SubElement(project_node, "name").text = project_name
    children = ET.SubElement(project_node, "children")
    sequence = ET.SubElement(children, "sequence", {"id": "sequence-1"})
    ET.SubElement(sequence, "name").text = project_name
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _add_rate(sequence)

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    _add_video_format(video)
    video_track = ET.SubElement(video, "track")
    title_track = ET.SubElement(video, "track")
    audio = ET.SubElement(media, "audio")
    _add_audio_format(audio)
    audio_track = ET.SubElement(audio, "track")

    spine = source_sequence.find("./spine")
    if spine is None:
        raise ValueError("FCPXML sequence has no spine")

    clip_count = 0
    for node in spine.findall("./asset-clip"):
        resource = resources.get(node.attrib.get("ref", ""))
        if resource is None:
            raise ValueError(f"FCPXML references unknown asset: {node.attrib.get('ref')}")
        _add_clipitem(video_track, node, resource, clip_count + 1, "video")
        clip_count += 1

    anchor = next(iter(spine), None)
    subtitle_count = 0
    if anchor is not None:
        for node in anchor.findall("./asset-clip"):
            resource = resources.get(node.attrib.get("ref", ""))
            if resource is None:
                raise ValueError(f"FCPXML references unknown asset: {node.attrib.get('ref')}")
            _add_clipitem(audio_track, node, resource, 1, "audio")
        for node in anchor.findall("./title"):
            _add_generatoritem(title_track, node, subtitle_count + 1)
            subtitle_count += 1

    if not list(video_track):
        video.remove(video_track)
    if not list(title_track):
        video.remove(title_track)
    if not list(audio_track):
        audio.remove(audio_track)

    output_path = get_final_premiere_xml_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    ET.fromstring(xml_body)
    temp_path = output_path.with_suffix(".xml.tmp")
    temp_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE xmeml>\n'
        f"{xml_body}\n",
        encoding="utf-8",
    )
    temp_path.replace(output_path)
    return {
        "path": str(output_path),
        "format": "premiere_xml",
        "xmeml_version": XMEML_VERSION,
        "fps": FPS,
        "duration_frames": total_frames,
        "clip_count": clip_count,
        "subtitle_count": subtitle_count,
        "source_fcpxml_path": str(source_path),
    }


def _add_clipitem(
    track: ET.Element,
    node: ET.Element,
    resource: ET.Element,
    index: int,
    media_type: str,
) -> None:
    start = _frames(node.attrib.get("offset", "0s"))
    duration = max(1, _frames(node.attrib.get("duration", "0s")))
    source_in = max(0, _frames(node.attrib.get("start", "0s")))
    source_out = source_in + duration
    time_points = node.findall("./timeMap/timept")
    if len(time_points) >= 2:
        source_in = max(0, _frames(time_points[0].attrib.get("value", "0s")))
        source_out = max(source_in + 1, _frames(time_points[-1].attrib.get("value", "0s")))
    source_duration = max(
        source_out,
        _frames(resource.attrib.get("duration", node.attrib.get("duration", "0s"))),
    )
    clip = ET.SubElement(track, "clipitem", {"id": f"{media_type}-clip-{index}"})
    ET.SubElement(clip, "name").text = resource.attrib.get("name", f"{media_type}-{index}")
    ET.SubElement(clip, "enabled").text = "TRUE"
    ET.SubElement(clip, "duration").text = str(source_duration)
    _add_rate(clip)
    ET.SubElement(clip, "start").text = str(start)
    ET.SubElement(clip, "end").text = str(start + duration)
    ET.SubElement(clip, "in").text = str(source_in)
    ET.SubElement(clip, "out").text = str(source_out)
    _add_file(clip, resource, index, media_type, source_duration)
    if media_type == "video" and source_out - source_in != duration:
        _add_speed_filter(clip, (source_out - source_in) / duration * 100)


def _add_file(
    clip: ET.Element,
    resource: ET.Element,
    index: int,
    media_type: str,
    duration: int,
) -> None:
    representation = resource.find("./media-rep")
    if representation is None or not representation.attrib.get("src"):
        raise ValueError(f"FCPXML asset has no media path: {resource.attrib.get('id')}")
    file_node = ET.SubElement(clip, "file", {"id": f"{media_type}-file-{index}"})
    ET.SubElement(file_node, "name").text = resource.attrib.get("name", f"{media_type}-{index}")
    ET.SubElement(file_node, "pathurl").text = _premiere_file_uri(representation.attrib["src"])
    ET.SubElement(file_node, "duration").text = str(duration)
    _add_rate(file_node)
    file_media = ET.SubElement(file_node, "media")
    if media_type == "audio":
        audio = ET.SubElement(file_media, "audio")
        characteristics = ET.SubElement(audio, "samplecharacteristics")
        ET.SubElement(characteristics, "depth").text = "16"
        ET.SubElement(characteristics, "samplerate").text = "48000"
        ET.SubElement(audio, "channelcount").text = resource.attrib.get("audioChannels", "2")
    else:
        video = ET.SubElement(file_media, "video")
        characteristics = ET.SubElement(video, "samplecharacteristics")
        ET.SubElement(characteristics, "width").text = "1920"
        ET.SubElement(characteristics, "height").text = "1080"


def _add_generatoritem(track: ET.Element, node: ET.Element, index: int) -> None:
    start = _frames(node.attrib.get("offset", "0s"))
    duration = max(1, _frames(node.attrib.get("duration", "0s")))
    text = node.findtext("./text/text-style", default="")
    item = ET.SubElement(track, "generatoritem", {"id": f"title-{index}"})
    ET.SubElement(item, "name").text = f"Subtitle {index}"
    ET.SubElement(item, "duration").text = str(duration)
    _add_rate(item)
    ET.SubElement(item, "start").text = str(start)
    ET.SubElement(item, "end").text = str(start + duration)
    ET.SubElement(item, "in").text = "0"
    ET.SubElement(item, "out").text = str(duration)
    effect = ET.SubElement(item, "effect")
    ET.SubElement(effect, "name").text = "Text"
    ET.SubElement(effect, "effectid").text = "Text"
    ET.SubElement(effect, "effectcategory").text = "Text"
    ET.SubElement(effect, "effecttype").text = "generator"
    ET.SubElement(effect, "mediatype").text = "video"
    parameter = ET.SubElement(effect, "parameter")
    ET.SubElement(parameter, "parameterid").text = "str"
    ET.SubElement(parameter, "name").text = "Text"
    ET.SubElement(parameter, "value").text = text


def _add_speed_filter(clip: ET.Element, speed_percent: float) -> None:
    filter_node = ET.SubElement(clip, "filter")
    effect = ET.SubElement(filter_node, "effect")
    ET.SubElement(effect, "name").text = "Time Remap"
    ET.SubElement(effect, "effectid").text = "timeremap"
    ET.SubElement(effect, "effectcategory").text = "motion"
    ET.SubElement(effect, "effecttype").text = "motion"
    ET.SubElement(effect, "mediatype").text = "video"
    variable = ET.SubElement(effect, "parameter", {"authoringApp": "PremierePro"})
    ET.SubElement(variable, "parameterid").text = "variablespeed"
    ET.SubElement(variable, "name").text = "variablespeed"
    ET.SubElement(variable, "value").text = "0"
    speed = ET.SubElement(effect, "parameter", {"authoringApp": "PremierePro"})
    ET.SubElement(speed, "parameterid").text = "speed"
    ET.SubElement(speed, "name").text = "speed"
    ET.SubElement(speed, "valuemin").text = "-100000"
    ET.SubElement(speed, "valuemax").text = "100000"
    ET.SubElement(speed, "value").text = f"{speed_percent:.6f}".rstrip("0").rstrip(".")
    reverse = ET.SubElement(effect, "parameter", {"authoringApp": "PremierePro"})
    ET.SubElement(reverse, "parameterid").text = "reverse"
    ET.SubElement(reverse, "name").text = "reverse"
    ET.SubElement(reverse, "value").text = "FALSE"


def _add_rate(parent: ET.Element) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(FPS)
    ET.SubElement(rate, "ntsc").text = "FALSE"


def _add_video_format(video: ET.Element) -> None:
    fmt = ET.SubElement(video, "format")
    characteristics = ET.SubElement(fmt, "samplecharacteristics")
    _add_rate(characteristics)
    ET.SubElement(characteristics, "width").text = "1920"
    ET.SubElement(characteristics, "height").text = "1080"
    ET.SubElement(characteristics, "anamorphic").text = "FALSE"
    ET.SubElement(characteristics, "pixelaspectratio").text = "square"
    ET.SubElement(characteristics, "fielddominance").text = "none"


def _add_audio_format(audio: ET.Element) -> None:
    fmt = ET.SubElement(audio, "format")
    characteristics = ET.SubElement(fmt, "samplecharacteristics")
    ET.SubElement(characteristics, "depth").text = "16"
    ET.SubElement(characteristics, "samplerate").text = "48000"


def _frames(value: str) -> int:
    text = str(value or "0s").strip()
    if not text.endswith("s"):
        raise ValueError(f"Unsupported FCPXML time value: {value}")
    seconds = Fraction(text[:-1] or "0")
    return round(seconds * FPS)


def _premiere_file_uri(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "file":
        raise ValueError(f"Premiere XML requires a local file URI: {value}")
    decoded_path = unquote(parsed.path)
    if len(decoded_path) >= 3 and decoded_path[0] == "/" and decoded_path[2] == ":":
        decoded_path = decoded_path[1:]
    normalized = Path(decoded_path).resolve().as_uri()
    if normalized.startswith("file:///"):
        return f"file://localhost/{normalized.removeprefix('file:///')}"
    return normalized
