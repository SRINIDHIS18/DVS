import os
import glob
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import google.generativeai as genai
from werkzeug.utils import secure_filename
from PIL import Image

# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = "super_secret_key"
UPLOAD_FOLDER = 'uploads'
SEAL_FOLDER = 'seals'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SEAL_FOLDER'] = SEAL_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SEAL_FOLDER, exist_ok=True)

# Update your API Key here
os.environ["GEMINI_API_KEY"] = "AIzaSyAlWkHLi3oQZ2qnMW2N6nJVTswDZ2WC658"
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

class DocumentVerificationSystem:
    def __init__(self, model_name="gemini-2.5-flash"):
        self.model = genai.GenerativeModel(model_name)

    def load_reference_seals(self):
        """Loads all valid images from the 'seals' folder."""
        seal_images = []
        files = glob.glob(os.path.join(app.config['SEAL_FOLDER'], '*'))
        for f in files:
            if f.split('.')[-1].lower() in ALLOWED_EXTENSIONS:
                try:
                    img = Image.open(f)
                    seal_images.append(img)
                except Exception as e:
                    print(f"Skipping invalid seal image {f}: {e}")
        return seal_images

    def verify_document(self, target_path, ref_path=None, doc_type="ID Card"):
        """
        Handles both Single and Dual document workflows dynamically.
        """
        # Get dynamic current date
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # 1. Prepare Base Content (Target Document)
        target_img = Image.open(target_path)
        content_parts = []
        
        # 2. Build the Prompt Dynamically
        base_prompt = f"""
        You are a Document Verification Specialist. 
        
        --- INPUTS ---
        1. **TARGET DOCUMENT** (First Image provided): Verify this document.
        """

        task_instructions = f"""
        --- TASKS ---
        1. **Data Extraction (Target Doc):**
           - Extract Name, ID Number, Date of Birth, and Expiry Date.
           - Check if the document is expired (Current Date: {current_date}).
           - Verify if it matches the document type: "{doc_type}".

        2. **Seal Verification (Target Doc):**
           - I have provided reference images of valid seals (after the documents).
           - check if ANY of these seals appear on the Target Document.
           - Ignore seals if no reference images are provided.
        """

        # Logic for Cross-Verification & Face Match (Only if Ref Path exists)
        if ref_path:
            ref_img = Image.open(ref_path)
            base_prompt += "\n2. **REFERENCE DOCUMENT / SELFIE** (Second Image provided): Use ONLY for info and face matching.\n"
            
            task_instructions += """
        3. **Cross-Check Information & Biometrics (Target vs Reference):**
           - Compare the **Name** and **ID Number** extracted from the Target against the Reference Document (if text exists).
           - **Biometric Check:** Compare the face on the Target Document to the face in the Reference Document/Selfie. Determine if they are the same person.
           - Do NOT verify the Reference Document's validity. Just read the text/faces.
            """
        else:
            task_instructions += """
        3. **Cross-Check Information & Biometrics:**
           - SKIPPED (No Reference Document/Selfie provided). Set "performed" to false.
            """

        # Final JSON Output instruction
        json_instruction = """
        --- OUTPUT ---
        Return strictly valid JSON:
        {
            "extracted_fields": { "Name": null, "ID_Number": null, "Date_of_Birth": null, "Expiry_Date": null },
            "verification_checks": {
                "document_type_match": boolean,
                "is_expired": boolean,
                "data_integrity": "valid" or "suspicious"
            },
            "seal_check": {
                "seal_detected": boolean,
                "confidence": "High" or "Low" or "None",
                "notes": "e.g. Found circular blue stamp"
            },
            "cross_match": {
                "performed": boolean,
                "match_found": boolean, 
                "details": "Details of text match or mismatch"
            },
            "biometric_check": {
                "performed": boolean,
                "face_match_confidence": "High" or "Low" or "None",
                "notes": "Brief explanation of facial similarities or differences"
            },
            "final_verdict": "APPROVE" or "REJECT",
            "reasoning": "Brief summary of findings."
        }
        """

        # Assemble the content list
        final_prompt = base_prompt + task_instructions + json_instruction
        
        content_parts.append(final_prompt)
        content_parts.append(target_img) # Image 1 (Target)

        if ref_path:
            content_parts.append(ref_img) # Image 2 (Reference/Selfie)

        # Add Seal Images at the end
        seal_imgs = self.load_reference_seals()
        if seal_imgs:
            content_parts.append(f"The following {len(seal_imgs)} images are VALID REFERENCE SEALS. Search for them on the Target Document.")
            content_parts.extend(seal_imgs)

        try:
            response = self.model.generate_content(
                content_parts,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            return {"final_verdict": "ERROR", "reasoning": f"AI Error: {str(e)}"}

# --- FLASK ROUTES ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # 1. Handle Target File (Mandatory)
        target_file = request.files.get('target_file')
        ref_file = request.files.get('ref_file') # Optional
        doc_type = request.form.get('doc_type', 'ID Card')

        if not target_file or target_file.filename == '':
            flash('Target document is required.')
            return redirect(request.url)

        if allowed_file(target_file.filename):
            # Save Target
            t_filename = secure_filename(target_file.filename)
            t_path = os.path.join(app.config['UPLOAD_FOLDER'], t_filename)
            target_file.save(t_path)

            # Save Reference (Only if uploaded)
            r_path = None
            if ref_file and ref_file.filename != '' and allowed_file(ref_file.filename):
                r_filename = secure_filename(ref_file.filename)
                r_path = os.path.join(app.config['UPLOAD_FOLDER'], r_filename)
                ref_file.save(r_path)

            # 2. Run Verification
            system = DocumentVerificationSystem()
            result = system.verify_document(t_path, r_path, doc_type)

            return render_template('index.html', result=result)

    return render_template('index.html', result=None)

if __name__ == '__main__':
    app.run(debug=True)