import re
import os
import pymupdf4llm

class MarkdownProcessor:
    """
    A helper class to extract markdown image entries and
    update descriptions based on image_id.
    """

    # regex for markdown images: ![alt](path)
    _pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)\)')

    @classmethod
    def extract_images(cls, md_text):
        """
        Returns list of {"path": path, "image_id": image_id}
        image_id = basename without extension
        """
        images = []
        for m in cls._pattern.finditer(md_text):
            path = m.group(2)
            basename = os.path.basename(path)
            image_id = os.path.splitext(basename)[0]
            images.append({"path": path, "image_id": image_id})
        return images

    @classmethod
    def insert_description_by_id(cls, md_text, image_id, description):
        """
        Replace the description for an image whose basename == image_id.
        """

        def repl(m):
            old_path = m.group(2)
            candidate_id = os.path.splitext(os.path.basename(old_path))[0]

            if candidate_id == image_id:
                # Insert new description
                return f'![{description}]({old_path})'

            return m.group(0)

        return cls._pattern.sub(repl, md_text)

    @classmethod
    def replace_path_with_tg_protocol(cls, md_text, image_id, tg_reference):
        """
        Replace the file path for an image whose basename == image_id with tg:// protocol reference.
        tg_reference should be like 'Graphs_image_1'
        """
        def repl(m):
            old_path = m.group(2)
            candidate_id = os.path.splitext(os.path.basename(old_path))[0]

            if candidate_id == image_id:
                # Replace path with tg:// protocol reference
                alt_text = m.group(1)
                return f'![{alt_text}](tg://{tg_reference})'

            return m.group(0)

        return cls._pattern.sub(repl, md_text)