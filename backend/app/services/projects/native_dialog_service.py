import threading
from pathlib import Path


_dialog_lock = threading.Lock()


def select_directory(initial_path: str | None = None, title: str = "选择文件夹") -> str | None:
    """Open the operating system's folder picker for this local application."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境不支持系统文件夹选择窗口") from exc

    initial_directory = _existing_directory(initial_path)
    with _dialog_lock:
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            selected = filedialog.askdirectory(
                parent=root,
                title=title,
                initialdir=str(initial_directory) if initial_directory else None,
                mustexist=True,
            )
        except tk.TclError as exc:
            raise RuntimeError("系统文件夹选择窗口无法打开") from exc
        finally:
            if root is not None:
                root.destroy()

    return str(Path(selected).resolve()) if selected else None


def _existing_directory(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).expanduser().resolve()
    return candidate if candidate.is_dir() else None
