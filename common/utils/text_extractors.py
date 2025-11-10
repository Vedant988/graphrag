"""
Text extraction utilities for various file formats.
This module handles the extraction of text content from different document types.
"""
import os
import json
import logging
import uuid
import base64
import io
from pathlib import Path
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class TextExtractor:
    """Class for handling text extraction from various file formats and cleanup."""

    def __init__(self):
        """Initialize the TextExtractor."""
        self.supported_extensions = {
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.json': 'application/json',
            '.csv': 'text/csv',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.xml': 'application/xml',
            '.jpeg': 'image/jpeg',
            '.jpg': 'image/jpeg'
        }

    async def _process_file_async(self, file_path, folder_path_obj, graphname):
        """
        Async helper to process a single file.
        Runs in thread pool to avoid blocking on I/O operations.
        """
        try:
            loop = asyncio.get_event_loop()

            doc_entries = await loop.run_in_executor(
                None,
                extract_text_from_file_with_images_as_docs,
                file_path,
                graphname
            )

            return {
                'success': True,
                'file_path': str(file_path),
                'documents': doc_entries,
                'num_documents': len(doc_entries)
            }

        except FileNotFoundError:
            return {'success': False, 'file_path': str(file_path), 'error': 'File not found'}
        except PermissionError:
            return {'success': False, 'file_path': str(file_path), 'error': 'Permission denied'}
        except Exception as e:
            logger.warning(f"Failed to process file {file_path}: {e}")
            return {'success': False, 'file_path': str(file_path), 'error': str(e)}

    async def _process_folder_async(self, folder_path, graphname=None, max_concurrent=10):
        """
        Async version of process_folder for parallel file processing.
        This prevents conflicts when multiple users process folders simultaneously.
        """
        logger.info(f"Processing local folder ASYNC: {folder_path} for graph: {graphname} (max_concurrent={max_concurrent})")

        folder_path_obj = Path(folder_path)

        if not folder_path_obj.exists():
            raise Exception(f"Folder path does not exist: {folder_path}")

        if not folder_path_obj.is_dir():
            raise Exception(f"Path is not a directory: {folder_path}")

        def safe_walk(path):
            try:
                for item in path.iterdir():
                    if item.name.startswith(('.', '~', '$')) or 'BROMIUM' in item.name.upper():
                        continue
                    if item.is_file():
                        yield item
                    elif item.is_dir():
                        yield from safe_walk(item)
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot access directory {path}: {e}")

        files_to_process = []
        for file_path in safe_walk(folder_path_obj):
            if file_path.is_file():
                if file_path.name.startswith(('.', '~', '$')) or 'BROMIUM' in file_path.name.upper():
                    continue
                file_ext = file_path.suffix.lower()
                if file_ext in self.supported_extensions:
                    files_to_process.append(file_path)

        logger.info(f"Found {len(files_to_process)} files to process")

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(file_path):
            async with semaphore:
                return await self._process_file_async(file_path, folder_path_obj, graphname)

        tasks = [process_with_semaphore(fp) for fp in files_to_process]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_documents = []
        processed_files_info = []

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"File processing failed with exception: {result}")
                continue

            if result.get('success'):
                all_documents.extend(result.get('documents', []))
                processed_files_info.append({
                    'file_path': result['file_path'],
                    'num_documents': result.get('num_documents', len(result.get('documents', []))),
                    'status': 'success'
                })
            else:
                processed_files_info.append({
                    'file_path': result['file_path'],
                    'status': 'failed',
                    'error': result.get('error', 'Unknown error')
                })

        logger.info(f"Processed {len(processed_files_info)} files, extracted {len(all_documents)} total documents")

        return {
            'statusCode': 200,
            'message': f'Processed {len(processed_files_info)} files, {len(all_documents)} documents',
            'documents': all_documents,
            'files': processed_files_info,
            'num_documents': len(all_documents)
        }

    def process_folder(self, folder_path, graphname=None):
        """
        Process local folder with multiple file formats and extract text content.
        Uses async processing internally for parallel file handling.
        """
        logger.info(f"Processing local folder: {folder_path} for graph: {graphname}")
        return asyncio.run(self._process_folder_async(folder_path, graphname))


def extract_text_from_file_with_images_as_docs(file_path, graphname=None):
    """
    Extract text and images from a file, treating images as separate document entries.
    """
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    base_doc_id = str(file_path.stem)

    logger.debug(f"Extracting with images as docs: {file_path} (type: {extension})")

    if extension == '.pdf':
        return _extract_pdf_with_images_as_docs(file_path, base_doc_id, graphname)
    elif extension in ['.jpeg', '.jpg', '.png', '.gif']:
        return _extract_standalone_image_as_doc(file_path, base_doc_id, graphname)
    else:
        content = extract_text_from_file(file_path, graphname)
        doc_type = get_doc_type_from_extension(extension)
        return [{
            "doc_id": base_doc_id,
            "doc_type": doc_type,
            "content": content,
            "position": 0
        }]


def _extract_pdf_with_images_as_docs(file_path, base_doc_id, graphname=None):
    """
    Extract PDF as ONE markdown document with inline image references.
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image as PILImage

        doc = fitz.open(file_path)
        markdown_parts = []
        image_entries = []
        image_counter = 0

        for page_num, page in enumerate(doc, start=1):
            if page_num > 1:
                markdown_parts.append("\n\n")
            markdown_parts.append(f"--- Page {page_num} ---\n\n")

            blocks = page.get_text("blocks", sort=True)
            text_blocks_with_pos = []

            for block in blocks:
                block_type = block[6] if len(block) > 6 else 0
                if block_type == 0:
                    text = block[4].strip()
                    if text:
                        y_pos = block[1]
                        text_blocks_with_pos.append({'type': 'text', 'content': text, 'y_pos': y_pos})

            image_list = page.get_images(full=True)
            images_with_pos = []

            if image_list:
                for img_index, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        img_rects = page.get_image_rects(xref)
                        y_pos = img_rects[0].y0 if img_rects else 999999

                        pil_image = PILImage.open(io.BytesIO(image_bytes))
                        if pil_image.width < 100 or pil_image.height < 100:
                            continue

                        from common.utils.image_data_extractor import describe_image_with_llm
                        description = describe_image_with_llm(pil_image)
                        description_lower = description.lower()
                        logo_indicators = [
                            'logo:', 'icon:', 'logo', 'icon', 'branding',
                            'watermark', 'trademark', 'stylized letter',
                            'stylized text', 'word "', "word '"
                        ]
                        if any(indicator in description_lower for indicator in logo_indicators):
                            continue

                        buffer = io.BytesIO()
                        if pil_image.mode != 'RGB':
                            pil_image = pil_image.convert('RGB')
                        pil_image.save(buffer, format="JPEG", quality=95)
                        image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

                        image_counter += 1
                        image_doc_id = f"{base_doc_id}_image_{image_counter}"

                        images_with_pos.append({
                            'type': 'image',
                            'image_doc_id': image_doc_id,
                            'description': description,
                            'y_pos': y_pos,
                            'image_data': image_base64,
                            'image_format': image_ext,
                            'width': pil_image.width,
                            'height': pil_image.height
                        })
                    except Exception as img_error:
                        logger.warning(f"Failed to extract image on page {page_num}: {img_error}")

            all_elements = text_blocks_with_pos + images_with_pos
            all_elements.sort(key=lambda x: x['y_pos'])

            for element in all_elements:
                if element['type'] == 'text':
                    markdown_parts.append(element['content'])
                    markdown_parts.append("\n\n")
                else:
                    markdown_parts.append("### Image Description\n\n")
                    markdown_parts.append(element['description'])
                    markdown_parts.append(f"\n\n[IMAGE_REF:{element['image_doc_id']}]\n\n")

                    image_entries.append({
                        "doc_id": element['image_doc_id'],
                        "doc_type": "image",
                        "image_description": element['description'],
                        "image_data": element['image_data'],
                        "image_format": element['image_format'],
                        "parent_doc": base_doc_id,
                        "page_number": page_num,
                        "width": element['width'],
                        "height": element['height'],
                        "position": int(element['image_doc_id'].split('_')[-1])
                    })

        doc.close()

        markdown_content = "".join(markdown_parts) if markdown_parts else "[No content extracted from PDF]"
        result = [{
            "doc_id": base_doc_id,
            "doc_type": "markdown",
            "content": markdown_content,
            "position": 0
        }]
        result.extend(image_entries)
        return result

    except ImportError:
        logger.error("PyMuPDF not available")
        return [{
            "doc_id": base_doc_id,
            "doc_type": "markdown",
            "content": "[PDF extraction requires PyMuPDF]",
            "position": 0
        }]
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
        raise


def _extract_standalone_image_as_doc(file_path, base_doc_id, graphname=None):
    """
    Extract standalone image file as ONE markdown document with inline image reference.
    """
    try:
        from PIL import Image as PILImage
        from common.utils.image_data_extractor import describe_image_with_llm

        pil_image = PILImage.open(file_path)
        if pil_image.width < 100 or pil_image.height < 100:
            return [{
                "doc_id": base_doc_id,
                "doc_type": "markdown",
                "content": f"[Skipped small image: {file_path.name}]",
                "position": 0
            }]

        description = describe_image_with_llm(pil_image)
        description_lower = description.lower()
        logo_indicators = ['logo:', 'icon:', 'logo', 'icon', 'branding',
                           'watermark', 'trademark', 'stylized letter',
                           'stylized text', 'word "', "word '"]
        if any(indicator in description_lower for indicator in logo_indicators):
            return [{
                "doc_id": base_doc_id,
                "doc_type": "markdown",
                "content": f"[Skipped logo/icon: {file_path.name}]",
                "position": 0
            }]

        buffer = io.BytesIO()
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        pil_image.save(buffer, format="JPEG", quality=95)
        image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        image_id = f"{base_doc_id}_image_1"
        content = f"{description}\n\n[IMAGE_REF:{image_id}]"

        return [
            {
                "doc_id": base_doc_id,
                "doc_type": "image",
                "content": content,
                "position": 0
            },
            {
                "doc_id": image_id,
                "doc_type": "image",
                "image_description": description,
                "image_data": image_base64,
                "image_format": "jpg",
                "parent_doc": base_doc_id,
                "page_number": 0,
                "width": pil_image.width,
                "height": pil_image.height,
                "position": 1
            }
        ]

    except Exception as e:
        logger.error(f"Error extracting image: {e}")
        return [{
            "doc_id": base_doc_id,
            "doc_type": "markdown",
            "content": f"[Image extraction failed: {str(e)}]",
            "position": 0
        }]


def extract_text_from_file(file_path, graphname=None):
    """
    Extract text content from a file based on its extension.
    """
    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    logger.debug(f"Extracting text from {file_path} (type: {extension}) for graph: {graphname}")

    try:
        if extension in ['.txt', '.md']:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        elif extension in ['.html', '.htm', '.csv']:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        elif extension == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif extension == '.docx':
            import docx
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        elif extension == '.xml':
            import xml.etree.ElementTree as ET
            tree = ET.parse(file_path)
            root = tree.getroot()

            def extract_text_from_element(element):
                text = element.text or ""
                for child in element:
                    text += " " + extract_text_from_element(child)
                if element.tail:
                    text += " " + element.tail
                return text.strip()

            content = extract_text_from_element(root)
            import re
            return re.sub(r'\s+', ' ', content).strip()
        else:
            return f"[Unsupported file type: {extension}]"

    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {e}")
        raise Exception(f"Text extraction failed: {e}")


def get_doc_type_from_extension(extension):
    """Map file extension to a chunker-compatible document type."""
    if not extension.startswith('.'):
        extension = '.' + extension
    extension = extension.lower()

    if extension in ['.html', '.htm']:
        return 'html'
    elif extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
        return 'image'
    else:
        return 'markdown'


def get_supported_extensions():
    """Get list of supported file extensions."""
    return {'.txt', '.md', '.html', '.htm', '.csv', '.json', '.pdf', '.docx', '.xml', '.jpeg', '.jpg', '.png', '.gif'}


def is_supported_file(file_path):
    """Check if a file is supported for text extraction."""
    extension = Path(file_path).suffix.lower()
    return extension in get_supported_extensions()
