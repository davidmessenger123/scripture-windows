import html
import os
import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QFileDevice, QIODevice, QMimeData, QRectF, QSaveFile, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QImageReader, QPainter, QPen
from PySide6.QtWidgets import QFileDialog

from .secure_files import (
    create_owner_only_directory,
    descriptor_identity,
    fsync_directory,
    open_file_no_follow,
    owner_only_handle_valid,
    restrict_handle_owner_only,
    windows_handle_identity,
)

CARD_WIDTH = 1080
CARD_HEIGHT = 1350
MAX_CARD_BYTES = 8 * 1024 * 1024
MAX_CARD_TEXT_BYTES = 48 * 1024
MAX_CARD_LINE_BYTES = 4096
MAX_CARD_LINES = 80
MAX_CARD_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PASSAGE_LAYOUT_HEIGHT = 700
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class ShareError(RuntimeError):
    pass


def format_plain_text(before: str, focal: str, after: str, reference: str, translation_name: str) -> str:
    before_text = _bounded_text(before, MAX_CARD_TEXT_BYTES // 2, "verse text")
    focal_text = _bounded_text(focal, MAX_CARD_TEXT_BYTES // 2, "verse text")
    after_text = _bounded_text(after, MAX_CARD_TEXT_BYTES // 2, "verse text")
    reference_text = _bounded_text(reference, 120, "verse reference")
    translation_text = _bounded_text(translation_name, 64, "translation name")
    passage = " ".join(part for part in (before_text, focal_text, after_text) if part)
    if not passage:
        raise ShareError("there is no verse to share")
    lines = [passage, "", "— %s" % reference_text]
    if translation_text:
        lines.append(translation_text)
    result = "\n".join(lines).strip()
    if _utf8_size(result) > MAX_CARD_TEXT_BYTES:
        raise ShareError("verse text is too large to share")
    return result


def render_card(text: str) -> QImage:
    source = _bounded_text(text, MAX_CARD_TEXT_BYTES, "verse text")
    if not source:
        raise ShareError("there is no verse to share")
    lines = source.splitlines()
    if len(lines) > MAX_CARD_LINES or any(_utf8_size(line) > MAX_CARD_LINE_BYTES for line in lines):
        raise ShareError("verse text is too large to share")
    reference_index = next((index for index, line in enumerate(lines) if line.strip().startswith("— ")), -1)
    passage_lines = [line.strip() for line in lines[:reference_index if reference_index >= 0 else len(lines)] if line.strip()]
    trailing = [line.strip() for line in lines[reference_index + 1:] if line.strip()] if reference_index >= 0 else []
    reference = lines[reference_index].strip()[2:].strip() if reference_index >= 0 else ""
    translation = trailing[0] if trailing else ""
    if _utf8_size(reference) > 120 or _utf8_size(translation) > 64:
        raise ShareError("verse metadata exceeds the size limit")
    if not passage_lines:
        raise ShareError("there is no verse to share")
    passage = " ".join(passage_lines)
    image = QImage(CARD_WIDTH, CARD_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull() or image.sizeInBytes() > MAX_CARD_IMAGE_BYTES:
        raise ShareError("could not allocate the verse card")
    image.fill(QColor("#0d1b2a"))
    painter = QPainter(image)
    if not painter.isActive():
        raise ShareError("could not initialize the verse card")
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(QPen(QColor("#24354a"), 3))
    painter.drawRoundedRect(QRectF(54, 54, CARD_WIDTH - 108, CARD_HEIGHT - 108), 34, 34)
    painter.setPen(QColor("#f5c542"))
    cross = QRectF(CARD_WIDTH / 2 - 22, 112, 44, 126)
    painter.drawRoundedRect(cross, 9, 9)
    painter.drawRoundedRect(QRectF(CARD_WIDTH / 2 - 72, 153, 144, 38), 9, 9)
    painter.setPen(QColor("#f5c542"))
    painter.setFont(_font(18, QFont.Weight.DemiBold, 3))
    painter.drawText(QRectF(100, 72, CARD_WIDTH - 200, 40), Qt.AlignmentFlag.AlignCenter, "SCRIPTURE")
    painter.setPen(QColor("#b9c3cf"))
    painter.setFont(_font(20, QFont.Weight.Medium, 2))
    painter.drawText(QRectF(100, 270, CARD_WIDTH - 200, 50), Qt.AlignmentFlag.AlignCenter, translation)
    passage_doc = _document(passage, 44, QColor("#ffffff"), 880, 150)
    passage_height = passage_doc.size().height()
    if passage_height > MAX_PASSAGE_LAYOUT_HEIGHT:
        painter.end()
        raise ShareError("verse text is too long to fit on the card")
    painter.save()
    painter.translate(100, 350)
    passage_doc.drawContents(painter)
    painter.restore()
    reference_y = min(1120, 350 + passage_height + 42)
    painter.setPen(QColor("#faa968"))
    painter.setFont(_font(25, QFont.Weight.DemiBold, 1))
    painter.drawText(QRectF(100, reference_y, CARD_WIDTH - 200, 50), Qt.AlignmentFlag.AlignCenter, reference)
    painter.setPen(QColor("#6f8296"))
    painter.setFont(_font(15, 400, 1))
    painter.drawText(QRectF(100, CARD_HEIGHT - 92, CARD_WIDTH - 200, 30), Qt.AlignmentFlag.AlignCenter, "A VERSE FOR TODAY")
    painter.end()
    return image


def _encoded_png(image: QImage) -> QByteArray:
    if image.isNull() or image.width() != CARD_WIDTH or image.height() != CARD_HEIGHT:
        raise ShareError("verse card image is invalid")
    if image.sizeInBytes() > MAX_CARD_IMAGE_BYTES:
        raise ShareError("verse card image is too large")
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise ShareError("could not encode the verse card")
    buffer.close()
    if not data or len(data) > MAX_CARD_BYTES:
        raise ShareError("encoded verse card exceeds the size limit")
    reader_buffer = QBuffer(data)
    if not reader_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ShareError("could not validate the verse card")
    reader = QImageReader()
    reader.setDevice(reader_buffer)
    reader.setFormat(b"PNG")
    if not reader.canRead() or reader.size().width() != CARD_WIDTH or reader.size().height() != CARD_HEIGHT:
        raise ShareError("encoded verse card failed validation")
    return QByteArray(data)


def copy_plain_text(text: str) -> None:
    value = _bounded_text(text, MAX_CARD_TEXT_BYTES, "verse text")
    if not value:
        raise ShareError("there is no verse to copy")
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise ShareError("the system clipboard is unavailable")
    clipboard.setText(value)


def copy_image(image: QImage) -> None:
    if image.isNull() or image.width() != CARD_WIDTH or image.height() != CARD_HEIGHT or image.sizeInBytes() > MAX_CARD_IMAGE_BYTES:
        raise ShareError("verse card image is invalid")
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise ShareError("the system clipboard is unavailable")
    clipboard.setImage(image)


def copy_card(text: str, image: QImage) -> None:
    value = _bounded_text(text, MAX_CARD_TEXT_BYTES, "verse text")
    if not value:
        raise ShareError("there is no verse to copy")
    data = _encoded_png(image)
    mime = QMimeData()
    mime.setText(value)
    mime.setData("image/png", bytes(data))
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise ShareError("the system clipboard is unavailable")
    clipboard.setMimeData(mime)


def choose_and_save_card(text: str, image: QImage, reference: str) -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    if pictures:
        base = Path(pictures) / "Scripture"
    else:
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        base = Path(app_data or str(Path.home())) / "shared-cards"
    try:
        create_owner_only_directory(base)
    except OSError as exc:
        raise ShareError("card share directory is unavailable") from exc
    default_path = str(base / default_filename(reference))
    selected, _ = QFileDialog.getSaveFileName(None, "Save Scripture card", default_path, "PNG image (*.png)")
    if not selected:
        return ""
    path = Path(selected)
    if path.suffix.lower() != ".png":
        path = path.with_name(path.name + ".png")
    save_card_atomic(image, path)
    return str(path)


def save_card_atomic(image: QImage, path) -> str:
    data = _encoded_png(image)
    raw_path = os.fspath(path)
    if not raw_path or len(raw_path) > 32767 or any(ord(char) < 32 for char in raw_path):
        raise ShareError("card path is invalid")
    target = Path(raw_path)
    if not target.is_absolute() or target.name in {"", ".", ".."} or target.suffix.lower() != ".png":
        raise ShareError("card path must be an absolute PNG file")
    try:
        parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise ShareError("card directory is unavailable") from exc
    if not parent.is_dir():
        raise ShareError("card directory is unavailable")
    destination = parent / target.name
    if destination.is_symlink() or (destination.exists() and destination.is_dir()):
        raise ShareError("card destination is unavailable")
    writer = None
    committed = False
    try:
        writer = QSaveFile(str(destination))
        writer.setDirectWriteFallback(False)
        if not writer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise ShareError("could not open the verse card destination")
        writer.setPermissions(QFileDevice.Permission.ReadOwner | QFileDevice.Permission.WriteOwner)
        native_handle = int(writer.handle())
        if native_handle < 0:
            raise ShareError("could not access the verse card temporary file")
        restrict_handle_owner_only(native_handle)
        identity = windows_handle_identity(native_handle) if os.name == "nt" else descriptor_identity(native_handle)
        if writer.write(data) != len(data) or not writer.commit():
            raise ShareError("could not save the verse card")
        committed = True
        fd = open_file_no_follow(destination, os.O_RDONLY)
        try:
            if descriptor_identity(fd) != identity or not owner_only_handle_valid(fd):
                raise ShareError("committed verse card identity or permissions changed")
        finally:
            os.close(fd)
        fsync_directory(parent)
    except ShareError:
        raise
    except Exception as exc:
        raise ShareError("could not save the verse card") from exc
    finally:
        if writer is not None and not committed:
            try:
                writer.cancelWriting()
            except Exception:
                pass
    return str(destination)


def default_filename(reference: str) -> str:
    cleaned = _INVALID_FILENAME.sub("-", str(reference or "verse")).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:80].strip(" .")
    return "%s-scripture-card.png" % (cleaned or "verse")


def _font(size: int, weight: int, letter_spacing: int) -> QFont:
    font = QFont("Sans Serif", size)
    font.setWeight(QFont.Weight(weight))
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return font


def _document(value: str, size: int, color: QColor, width: int, line_spacing: int):
    from PySide6.QtGui import QTextDocument

    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(_font(size, QFont.Weight.Light, 0))
    document.setHtml(
        '<div style="color:%s; font-size:%dpx; line-height:%d%%; text-align:center;">%s</div>'
        % (color.name(), size, line_spacing, html.escape(str(value or ""), quote=False))
    )
    document.setTextWidth(width)
    document.setUndoRedoEnabled(False)
    return document


def _utf8_size(value: str) -> int:
    try:
        return len(str(value).encode("utf-8"))
    except UnicodeError as exc:
        raise ShareError("verse text is not valid Unicode") from exc


def _bounded_text(value: str, limit: int, label: str) -> str:
    text = str(value or "").strip()
    if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text):
        raise ShareError("%s contains invalid control characters" % label)
    if _utf8_size(text) > limit:
        raise ShareError("%s exceeds the size limit" % label)
    return text
