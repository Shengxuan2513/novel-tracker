"""
EPUB3 Document Formatter.
Builds compliant standard EPUB e-books with TOC navigation, metadata, and typography using zipfile.
Zero external library dependencies required.
"""

import html
import os
import uuid
import zipfile
from datetime import datetime
from typing import List, Tuple, Dict


from core.safe_publish import atomic_export


class EpubFormatter:
    @staticmethod
    @atomic_export
    def export(
        output_path: str,
        book_meta: Dict[str, str],
        chapters: List[Tuple[int, str, str]],
        source_url: str = ""
    ) -> str:
        """
        Packs chapters into a standard EPUB3 container.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        book_title = book_meta.get("title", "未命名小说")
        author = book_meta.get("author", "未知")
        book_uuid = str(uuid.uuid4())
        try:
            from datetime import timezone
            mod_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            mod_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Create temporary in-memory or on-disk zip
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. mimetype (Must be uncompressed at index 0)
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

            # 2. META-INF/container.xml
            container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>"""
            zf.writestr("META-INF/container.xml", container_xml)

            # 3. OEBPS/style.css
            style_css = """body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.8;
    margin: 5% 8%;
    color: #2c3e50;
}
h1 {
    font-size: 1.5em;
    text-align: center;
    margin: 2em 0 1.5em 0;
    font-weight: bold;
}
p {
    text-indent: 2em;
    margin: 0.8em 0;
}"""
            zf.writestr("OEBPS/style.css", style_css)

            # 4. Chapters XHTML
            manifest_items = [
                '<item id="style" href="style.css" media-type="text/css"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            ]
            spine_items = []
            ncx_navpoints = []
            nav_toc_li = []

            for idx, title, content in chapters:
                escaped_title = html.escape(title)
                raw_lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
                # Skip first line if title is duplicated
                body_lines = raw_lines[1:] if len(raw_lines) > 1 and raw_lines[0] == title else raw_lines
                p_tags = "\n".join(f"    <p>{html.escape(p)}</p>" for p in body_lines)

                chapter_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head>
    <title>{escaped_title}</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    <h1>{escaped_title}</h1>
{p_tags}
</body>
</html>"""
                chap_filename = f"chapter_{idx}.xhtml"
                zf.writestr(f"OEBPS/{chap_filename}", chapter_xhtml)

                manifest_items.append(f'<item id="chap_{idx}" href="{chap_filename}" media-type="application/xhtml+xml"/>')
                spine_items.append(f'<itemref idref="chap_{idx}"/>')
                ncx_navpoints.append(f"""    <navPoint id="np_{idx}" playOrder="{idx}">
        <navLabel><text>{escaped_title}</text></navLabel>
        <content src="{chap_filename}"/>
    </navPoint>""")
                nav_toc_li.append(f'        <li><a href="{chap_filename}">{escaped_title}</a></li>')

            # 5. OEBPS/toc.ncx
            toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
    <head>
        <meta name="dtb:uid" content="{book_uuid}"/>
        <meta name="dtb:depth" content="1"/>
        <meta name="dtb:totalPageCount" content="0"/>
        <meta name="dtb:maxPageNumber" content="0"/>
    </head>
    <docTitle><text>{html.escape(book_title)}</text></docTitle>
    <docAuthor><text>{html.escape(author)}</text></docAuthor>
    <navMap>
{"".join(ncx_navpoints)}
    </navMap>
</ncx>"""
            zf.writestr("OEBPS/toc.ncx", toc_ncx)

            # 6. OEBPS/nav.xhtml
            nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head>
    <title>目录</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    <nav epub:type="toc" id="toc">
        <h1>目录</h1>
        <ol>
{"".join(nav_toc_li)}
        </ol>
    </nav>
</body>
</html>"""
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml)

            # 7. OEBPS/content.opf
            content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:identifier id="BookID">urn:uuid:{book_uuid}</dc:identifier>
        <dc:title>{html.escape(book_title)}</dc:title>
        <dc:creator>{html.escape(author)}</dc:creator>
        <dc:language>zh-CN</dc:language>
        <meta property="dcterms:modified">{mod_time}</meta>
    </metadata>
    <manifest>
        {"".join(manifest_items)}
    </manifest>
    <spine toc="ncx">
        {"".join(spine_items)}
    </spine>
</package>"""
            zf.writestr("OEBPS/content.opf", content_opf)

        return output_path
