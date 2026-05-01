import io
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask, render_template, request, send_file
from PIL import Image
from werkzeug.utils import secure_filename
 
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB limit
 
CROP_X, CROP_Y, CROP_W, CROP_H = 328, 1043, 1187, 1326
PASTE_X, PASTE_Y = 615, 1492
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
 
 
@app.route("/")
def index():
    return render_template("index.html")
 
 
def extract_images_from_upload(files):
    images = []
    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            continue
        if Path(filename).suffix.lower() == ".zip":
            data = io.BytesIO(f.read())
            with zipfile.ZipFile(data) as zf:
                for member in zf.namelist():
                    if Path(member).suffix.lower() in SUPPORTED and not member.startswith("__MACOSX"):
                        images.append((Path(member).name, io.BytesIO(zf.read(member))))
        elif Path(filename).suffix.lower() in SUPPORTED:
            images.append((filename, io.BytesIO(f.read())))
    return images
 
 
def process_one(args):
    filename, data, mode, template_bytes = args
    try:
        img = Image.open(data).convert("RGBA")
        cropped = img.crop((CROP_X, CROP_Y, CROP_X + CROP_W, CROP_Y + CROP_H))
 
        if mode == "composite":
            template = Image.open(io.BytesIO(template_bytes)).convert("RGBA")
            canvas = template.copy()
            canvas.paste(cropped, (PASTE_X, PASTE_Y), cropped)
            result = canvas
            out_name = Path(filename).stem + "_final.jpg"
        else:
            result = cropped
            out_name = Path(filename).stem + ".jpg"
 
        out = io.BytesIO()
        result.convert("RGB").save(out, "JPEG", quality=95)
        return (out_name, out.getvalue())
    except Exception:
        return None
 
 
@app.route("/process", methods=["POST"])
def process():
    qr_files = request.files.getlist("qr_images")
    template_file = request.files.get("template")
    mode = request.form.get("mode", "crop")
 
    if not qr_files or not qr_files[0].filename:
        return "No QR images uploaded.", 400
    if mode == "composite" and (not template_file or not template_file.filename):
        return "Template image is required for composite mode.", 400
 
    images = extract_images_from_upload(qr_files)
    if not images:
        return "No valid images found. Upload images or a zip file.", 400
 
    template_bytes = template_file.read() if mode == "composite" else None
 
    tasks = [(filename, data, mode, template_bytes) for filename, data in images]
 
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(process_one, tasks))
 
    zip_buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in results:
            if result:
                zf.writestr(result[0], result[1])
                count += 1
 
    if count == 0:
        return "No images could be processed.", 400
 
    zip_buffer.seek(0)
    download_name = "composited_images.zip" if mode == "composite" else "cropped_images.zip"
    return send_file(zip_buffer, as_attachment=True, download_name=download_name, mimetype="application/zip")
 
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
