import base64
import io
import logging
import os
import uuid
import hashlib
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage

from common.config import get_multimodal_service

logger = logging.getLogger(__name__)



def describe_image_with_llm(image_input):
    """
    Send image (pixmap or PIL image) to LLM vision model and return description.
    Uses multimodal_service from config if available, otherwise falls back to completion_service.
    Currently supports: OpenAI, Azure OpenAI, Google GenAI, and Google VertexAI
    """
    try:
        client = get_multimodal_service()
        if not client:
            return "[Image: Failed to create multimodal LLM client]"
        
        buffer = io.BytesIO()
        # Convert to RGB if needed for better compatibility
        if image_input.mode != 'RGB':
            image_input = image_input.convert('RGB')
        image_input.save(buffer, format="JPEG", quality=95)
        b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Build messages (system + human)
        messages = [
        SystemMessage(
            content="You are a helpful assistant that describes images concisely for document analysis."
        ),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                         "Please describe what you see in this image and "
                        "if the image has scanned text then extract all the text. "
                        "Focus on any text, diagrams, charts, or other visual elements."
                        "If this is a logo, icon, or branding element, start your response with 'LOGO:' or 'ICON:'."
                    ),
                },
                 {
                     "type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                 },
            ]
        ),
        ]

        # Get response from LangChain LLM client
        # Access the underlying LangChain client
        langchain_client = client.llm
        response = langchain_client.invoke(messages)

        return response.content if hasattr(response, 'content') else str(response)

    except Exception as e:
        logger.error(f"Failed to describe image with LLM: {str(e)}")
        return "[Image: Error processing image description]"


def save_image_and_get_markdown(image_input, context_info="", graphname=None):
    """
    Save image locally to static/images/ folder and return markdown reference with description.
    
    LEGACY/OLD APPROACH: Used for backward compatibility with JSONL-based loading.
    Images are saved as files and served via /ui/images/ endpoint with img:// protocol.
    
    For NEW direct loading approach, images are stored in Image vertex as base64
    and served via /ui/image_vertex/ endpoint with image:// protocol.
    
    Args:
        image_input: PIL Image object
        context_info: Optional context (e.g., "page 3 of invoice.pdf")
        graphname: Graph name to organize images by graph (optional)
    
    Returns:
        dict with:
            - 'markdown': Markdown string with img:// reference
            - 'image_id': Unique identifier for the saved image
            - 'image_path': Path where image was saved to static/images/
    """
    try:
        # FIRST: Get description from LLM to check if it's a logo
        description = describe_image_with_llm(image_input)
        
        # Check if the image is a logo, icon, or decorative element BEFORE saving
        # These should be filtered out as they're not content-relevant
        description_lower = description.lower()
        logo_indicators = ['logo', 'icon', 'branding', 'watermark', 'trademark', 'company logo', 'brand logo']
        
        if any(indicator in description_lower for indicator in logo_indicators):
            logger.info(f"Detected logo/icon in image, skipping: {description[:100]}")
            return None
        
        # If not a logo, proceed with saving the image
        # Generate unique image ID using hash of image content
        buffer = io.BytesIO()
        if image_input.mode != 'RGB':
            image_input = image_input.convert('RGB')
        image_input.save(buffer, format="JPEG", quality=95)
        image_bytes = buffer.getvalue()
        
        # Create hash-based ID (deterministic for same image)
        image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
        image_id = f"{image_hash}.jpg"
        
        # Save image to local storage directory organized by graphname
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # If graphname is provided, organize images by graph
        if graphname:
            images_dir = os.path.join(project_root, "static", "images", graphname)
            # Include graphname in the image reference for URL construction
            image_reference = f"{graphname}/{image_id}"
        else:
            images_dir = os.path.join(project_root, "static", "images")
            image_reference = image_id
        
        os.makedirs(images_dir, exist_ok=True)
        
        image_path = os.path.join(images_dir, image_id)
        
        # Save image file (skip if already exists with same hash)
        if not os.path.exists(image_path):
            with open(image_path, 'wb') as f:
                f.write(image_bytes)
            logger.info(f"Saved content image to: {image_path}")
        else:
            logger.debug(f"Image already exists: {image_path}")
        
        # Generate markdown with custom img:// protocol (will be replaced later)
        # Format: ![description](img://graphname/image_id) or ![description](img://image_id)
        markdown = f"![{description}](img://{image_reference})"
        
        logger.info(f"Created image reference: {image_reference} with description")
        
        return {
            'markdown': markdown,
            'image_id': image_reference,
            'image_path': image_path,
            'description': description
        }
        
    except Exception as e:
        logger.error(f"Failed to save image and generate markdown: {str(e)}")
        # Fallback to text description only
        fallback_desc = f"[Image: {context_info} - processing failed]"
        return {
            'markdown': fallback_desc,
            'image_id': None,
            'image_path': None,
            'description': fallback_desc
        }


