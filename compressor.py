import tinify, io, zipfile, tempfile, os
from PIL import Image

tinify.key = os.environ["TINIFY_API_KEY"]

def process_images(files):
    """files = list of UploadedFile objects"""
    box, landscape, portrait = [], [], []
    for f in files:
        name = f.name.lower()
        if "box" in name:
            box.append(f)
        elif "landscape" in name:
            landscape.append(f)
        elif "portrait" in name:
            portrait.append(f)

    # compress landscape & portrait with TinyPNG
    ok_files = []
    for group in (landscape + portrait):
        source = tinify.from_buffer(group.read())
        ok_files.append((group.name, source.to_buffer()))
    # leave box as-is
    for group in box:
        ok_files.append((group.name, group.read()))

    # zip everything in-memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in ok_files:
            z.writestr(name.replace(".png", ".webp"), data)
    buf.seek(0)
    return buf
