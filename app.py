import os
import io
from datetime import datetime
import re
import pdfplumber
import pdfkit

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin,
    login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ATS / text utils
from services.text_extractor import (
    extract_text_from_resume,
    extractresumefrompdf,      # <-- use your template-aware parser
)
from services.ats_formatter import ATSFormatter
from services.ats_normalizer import (
    make_resume_ats_friendly,
    normalize_skills,
    normalize_softskills,
    normalize_languages_spoken,
    normalize_block_section,
    normalize_date,
)
# ❌ REMOVE this line for uploads (you don’t need it there anymore):
# from services.ats_resume_enhancer import ATSResumeEnhancer


# ===================== APP SETUP =====================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart-resume-secret'

# DATABASE
DB_PATH = os.path.join(BASE_DIR, 'instance', 'smartresume.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# LOGIN
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# UPLOADS
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# PDF CONFIG
WKHTMLTOPDF_PATH = r"D:\wkhtmltopdf\bin\wkhtmltopdf.exe"  # change if needed
PDF_OPTIONS = {
    'enable-local-file-access': None,
    'quiet': '',
    'margin-top': '0.75in',
    'margin-right': '0.75in',
    'margin-bottom': '0.75in',
    'margin-left': '0.75in',
    'encoding': "UTF-8"
}
if os.path.exists(WKHTMLTOPDF_PATH):
    pdf_config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
else:
    pdf_config = None

# ===================== TEMPLATE META =====================
TEMPLATE_META = {
    'template1': {'label': 'Modern Professional', 'desc': 'Clean & ATS Friendly'},
    'template2': {'label': 'Corporate Blue', 'desc': 'Formal & Recruiter Ready'},
    'template3': {'label': 'Creative Minimal', 'desc': 'Stylish & Modern'},
    'template4': {'label': 'Executive Black', 'desc': 'Leadership & Premium'},
    'template5': {'label': 'Fresh Graduate', 'desc': 'Simple & Entry Level'},
    'template6': {'label': 'Purple Pro', 'desc': 'Modern & Premium'},
    'template7': {'label': 'Tech Focused', 'desc': 'Developer Friendly'},
    'template8': {'label': 'Classic Resume', 'desc': 'Traditional & Safe'},
    'template9': {'label': 'Elegant Grey', 'desc': 'Balanced & Professional'},
    'template10': {'label': 'Startup Ready', 'desc': 'Bold & Modern'},
    "template_adani": {
        "label": "Adani Corporate",
        "desc": "Clean, conservative corporate layout inspired by large Indian conglomerates"
    },
    "template_tcs": {
        "label": "TCS Fresher Format",
        "desc": "Single-column academic style"
    },
    "template_reliance": {
        "label": "Reliance / Core",
        "desc": "Two-column, experience-focused"
    },
    "template_it_modern": {
        "label": "IT Modern One-Page",
        "desc": "ATS-friendly product/IT style"
    },
}

# ===================== MODELS =====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Resume(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Metadata
    title = db.Column(db.String(120))
    template_name = db.Column(db.String(50), default='template1')

    # Personal Information
    fullname = db.Column(db.String(120))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    location = db.Column(db.String(120))
    profile_pic = db.Column(db.String(255))

    # Main Sections
    summary = db.Column(db.Text)
    skills = db.Column(db.Text)
    experience = db.Column(db.Text)
    education = db.Column(db.Text)
    projects = db.Column(db.Text)
    certifications = db.Column(db.Text)
    awards = db.Column(db.Text)
    languages = db.Column(db.Text)

    # Links
    linkedin = db.Column(db.String(500))
    github = db.Column(db.String(500))
    website = db.Column(db.String(500))

    # New personal/soft fields
    dob = db.Column(db.String(50))
    nationality = db.Column(db.String(100))
    softskills = db.Column(db.Text)
    career_objective = db.Column(db.Text)

    # ATS fields
    ats_compliance_score = db.Column(db.Integer, default=0)
    ats_issues = db.Column(db.Text)
    ats_recommendations = db.Column(db.Text)

    # Job matching
    job_match_score = db.Column(db.Integer, default=0)
    job_match_keywords = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Resume {self.id}: {self.title}>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===================== HELPERS =====================
def add_photo_url(resume):
    if hasattr(resume, 'profile_pic') and resume.profile_pic:
        resume.photo_url = url_for('static', filename=f'uploads/{resume.profile_pic}')
    else:
        resume.photo_url = None
    return resume


def get_default_16_fields():
    return {
        "title": "",
        'fullname': 'Your Name',
        'email': '',
        'phone': '',
        'location': '',
        'summary': 'PDF loaded successfully! Edit your details above.',
        'skills': '',
        'experience': '',
        'education': '',
        'projects': '',
        'certifications': '',
        'awards': '',
        'languages': '',
        'linkedin': '',
        'github': '',
        'website': '',
        'dob': '',
        'nationality': '',
        'softskills': '',
        'career_objective': '',
    }

# ===================== PDF EXTRACTION =====================
def extract_resume_from_pdf(pdf_path: str) -> dict:
    result = get_default_16_fields()
    try:
        all_text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    all_text += "\n" + page_text

        all_text = all_text.strip()
        if not all_text:
            return result

        lines = [ln.strip() for ln in all_text.splitlines() if ln.strip()]
        if not lines:
            return result

        # NAME
        for ln in lines[:15]:
            if "@" in ln or "http" in ln.lower() or "+91" in ln:
                continue
            words = ln.split()
            if 2 <= len(words) <= 4 and len(ln) < 50:
                alpha_count = sum(1 for c in ln if c.isalpha() or c.isspace())
                if alpha_count > 0 and alpha_count / len(ln) > 0.7:
                    result["fullname"] = ln
                    break

        # EMAIL
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", all_text)
        if m:
            result["email"] = m.group(0)

        # PHONE
        phone_patterns = [
            r"\+91[\s\-]?\d{10}",
            r"\b0\d{10}\b",
            r"\b\d{10}\b",
        ]
        phone = ""
        for pattern in phone_patterns:
            m = re.search(pattern, all_text)
            if m:
                phone = m.group(0)
                break
        if phone:
            result["phone"] = phone

        # LOCATION
        cities = [
            "ahmedabad", "gandhinagar", "vadodara", "surat",
            "delhi", "mumbai", "bangalore", "pune", "hyderabad",
            "kolkata", "firozabad", "india", "gujarat",
            "usa", "uk", "canada"
        ]
        for ln in lines:
            low = ln.lower()
            for city in cities:
                if city in low and len(ln) < 80:
                    result["location"] = ln
                    break
            if result["location"]:
                break
        if not result["location"]:
            for ln in lines[:10]:
                if "," in ln and any(c.isalpha() for c in ln):
                    result["location"] = ln
                    break

        # SOCIAL
        m = re.search(r"linkedin\.com[^\s]*", all_text, re.IGNORECASE)
        if m:
            url = m.group(0)
            result["linkedin"] = url if url.startswith("http") else "https://" + url

        m = re.search(r"github\.com[^\s]*", all_text, re.IGNORECASE)
        if m:
            url = m.group(0)
            result["github"] = url if url.startswith("http") else "https://" + url

        # SECTION HEADERS
        section_patterns = {
            "summary": [
                r"career\s+objective", r"^objective$", r"professional\s+summary",
                r"summary", r"profile", r"about\s+me"
            ],
            "skills": [
                r"technical\s+skills", r"^skills$", r"core\s+competencies",
                r"key\s+skills", r"skills\s+and\s+tools"
            ],
            "experience": [
                r"professional\s+experience", r"work\s+experience", r"^experience$",
                r"employment\s+history", r"career\s+history", r"internship\s+experience"
            ],
            "projects": [
                r"academic\s+projects", r"key\s+projects", r"^projects$",
                r"personal\s+projects"
            ],
            "education": [
                r"^education$", r"academic\s+background", r"educational\s+qualification",
                r"academic\s+qualifications", r"education\s+details"
            ],
            "certifications": [
                r"^certifications?$", r"professional\s+certifications?",
                r"licenses?", r"courses"
            ],
            "languages": [
                r"languages?\s+known", r"^languages?$"
            ],
            "awards": [
                r"^awards$", r"achievements", r"honors"
            ],
        }

        section_positions = {}
        for field, patterns in section_patterns.items():
            for i, ln in enumerate(lines):
                for pattern in patterns:
                    if re.search(pattern, ln, re.IGNORECASE):
                        section_positions[field] = i
                        break
                if field in section_positions:
                    break

        def get_section_content(field_name: str, max_lines: int = 30) -> list:
            if field_name not in section_positions:
                return []
            start = section_positions[field_name] + 1
            end = len(lines)
            for other_field, pos in section_positions.items():
                if pos > start and pos < end:
                    end = pos
            end = min(end, start + max_lines)
            content_lines = lines[start:end]
            filtered = []
            for ln in content_lines:
                if len(ln) < 10:
                    continue
                if re.match(r"^page\s+\d+", ln, re.IGNORECASE):
                    continue
                filtered.append(ln)
            return filtered

        summary_lines = get_section_content("summary", 10)
        if summary_lines:
            full_summary = " ".join(summary_lines)[:1000]
            result["summary"] = full_summary
            if any(re.search(r"career\s+objective", ln, re.IGNORECASE) for ln in lines):
                result["career_objective"] = full_summary

        skills_lines = get_section_content("skills", 20)
        if skills_lines:
            skills_text = " ".join(skills_lines)
            skills = re.split(r"[,•\|/\n]", skills_text)
            skills = [s.strip() for s in skills if 2 < len(s.strip()) < 80]
            result["skills"] = ", ".join(skills[:30])[:500]

        exp_lines = get_section_content("experience", 30)
        if not exp_lines:
            for ln in lines:
                if "experience" in ln.lower() and len(ln) < 70:
                    idx = lines.index(ln)
                    exp_lines = lines[idx+1: idx+15]
                    break
        if exp_lines:
            result["experience"] = "\n".join(exp_lines)[:1500]

        edu_lines = get_section_content("education", 20)
        if not edu_lines:
            degree_words = ["b.tech", "b.e", "bachelor", "master", "phd", "degree"]
            edu_lines = [ln for ln in lines if any(dw in ln.lower() for dw in degree_words)]
        if edu_lines:
            result["education"] = "\n".join(edu_lines)[:1000]

        proj_lines = get_section_content("projects", 30)
        if proj_lines:
            result["projects"] = "\n".join(proj_lines)[:800]

        cert_lines = get_section_content("certifications", 15)
        if cert_lines:
            result["certifications"] = "\n".join(cert_lines)[:800]

        lang_lines = get_section_content("languages", 5)
        if lang_lines:
            result["languages"] = ", ".join(lang_lines)[:300]

        award_lines = get_section_content("awards", 15)
        if award_lines:
            result["awards"] = "\n".join(award_lines)[:500]

        if not result["title"] or result["title"] == "My Resume":
            title_keywords = [
                "engineer", "developer", "analyst", "manager", "specialist",
                "consultant", "architect", "designer", "scientist", "executive",
                "coordinator",
            ]
            for ln in lines[:25]:
                if any(kw in ln.lower() for kw in title_keywords) and len(ln) < 100:
                    result["title"] = ln
                    break
            if result["title"] == "My Resume":
                if "data" in result["skills"].lower():
                    result["title"] = "Data Professional"
                elif "python" in result["skills"].lower():
                    result["title"] = "Software Developer"
                else:
                    result["title"] = "Professional"

    except Exception as e:
        print(f"❌ PDF extraction error: {e}")

    return result

# ===================== ROUTES =====================
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        fullname = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')

        if not fullname:
            return "fullname missing in form", 400

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('signup'))

        user = User(fullname=fullname, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Account created. Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid credentials', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    resumes = Resume.query.filter_by(user_id=current_user.id).all()
    for resume in resumes:
        add_photo_url(resume)
    return render_template('dashboard.html', resumes=resumes, templates=TEMPLATE_META)


@app.route('/templates')
@login_required
def choose_template():
    return render_template('choose_template.html', templates=TEMPLATE_META)


@app.route('/resume/new/<template>')
@login_required
def new_resume(template):
    resume = Resume(
        user_id=current_user.id,
        title=f"New Resume - {current_user.fullname}", 
        template_name=template,
        fullname=current_user.fullname or '',
        email=current_user.email,
        dob="",
        nationality="Indian",
        softskills="",
        career_objective=""
    )
    db.session.add(resume)
    db.session.commit()
    return redirect(url_for('edit_resume', resume_id=resume.id))

@app.route('/resume/edit/<int:resume_id>', methods=['GET', 'POST'])
@login_required
def edit_resume(resume_id):
    resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        resume.title = request.form.get('title') or resume.title or 'My Resume'
        resume.fullname = request.form.get('fullname') or resume.fullname
        resume.email = request.form.get('email') or resume.email
        resume.phone = request.form.get('phone') or resume.phone
        resume.location = request.form.get('location') or resume.location

        dob_raw = request.form.get('dob') or resume.dob
        resume.dob = normalize_date(dob_raw) if dob_raw else resume.dob

        resume.nationality = (request.form.get('nationality') or resume.nationality or '').strip()

        summary_raw = request.form.get('summary') or resume.summary or ''
        resume.summary = '. '.join(summary_raw.split('.')) if summary_raw else ''

        careerobjective_raw = request.form.get('careerobjective') or resume.career_objective or ''
        resume.career_objective = '. '.join(careerobjective_raw.split('.')) if careerobjective_raw else ''

        resume.skills = normalize_skills(request.form.get('skills') or resume.skills or '')
        resume.softskills = normalize_softskills(request.form.get('softskills') or resume.softskills or '')
        resume.languages = normalize_languages_spoken(request.form.get('languages') or resume.languages or '')
        resume.experience = normalize_block_section(request.form.get('experience') or resume.experience or '')
        resume.education = normalize_block_section(request.form.get('education') or resume.education or '')
        resume.projects = normalize_block_section(request.form.get('projects') or resume.projects or '')
        resume.certifications = normalize_block_section(request.form.get('certifications') or resume.certifications or '')
        resume.awards = normalize_block_section(request.form.get('awards') or resume.awards or '')
        resume.linkedin = request.form.get('linkedin') or resume.linkedin
        resume.github = request.form.get('github') or resume.github
        resume.website = request.form.get('website') or resume.website

        file = request.files.get('profile_pic') or request.files.get('profilepic')
        if file and file.filename:
            filename = secure_filename(
                f"{current_user.id}_{resume_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
            )
            uploadpath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(uploadpath)
            resume.profile_pic = filename

        db.session.commit()
        flash(f"Saved! Title: {resume.title}", "success")
        return redirect(url_for('view_resume', resume_id=resume.id))

    return render_template('edit_resume.html', resume=resume, prefilled=None)


@app.route('/resume/view/<int:resume_id>', methods=['GET', 'POST'])
@login_required
def view_resume(resume_id):
    resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        resume.template_name = request.form.get('template_name')
        db.session.commit()

    add_photo_url(resume)
    return render_template('view_resume.html', resume=resume, templates=TEMPLATE_META)


@app.route('/resume/download/<int:resume_id>')
@login_required
def download_pdf(resume_id):
    resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first_or_404()
    add_photo_url(resume)

    if not pdf_config:
        flash("PDF engine not configured", "danger")
        return redirect(url_for('view_resume', resume_id=resume.id))

    html = render_template(f'pdf/{resume.template_name}.html', resume=resume)
    pdf = pdfkit.from_string(html, False, configuration=pdf_config, options=PDF_OPTIONS)
    return send_file(io.BytesIO(pdf), download_name=f'{resume.title or "resume"}.pdf', as_attachment=True)


@app.route('/resume/delete/<int:resume_id>')
@login_required
def delete_resume(resume_id):
    resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first_or_404()
    db.session.delete(resume)
    db.session.commit()
    flash('Resume deleted', 'success')
    return redirect(url_for('dashboard'))


@app.route('/pdf/<template_name>.html')
@login_required
def pdf_template(template_name):
    resume_id = request.args.get('resume_id')
    if not resume_id:
        return "Resume ID required", 400
    resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first_or_404()
    add_photo_url(resume)
    return render_template(f'pdf/{template_name}.html', resume=resume)


@app.route('/preview-template/<template_name>')
def preview_template(template_name):
    dummy_resume = {
        'fullname': 'John Doe',
        'title': 'Senior Software Engineer',
        'email': 'john.doe@email.com',
        'phone': '+1 (555) 123-4567',
        'location': 'San Francisco, CA',
        'summary': 'Results-driven software engineer with 7+ years of experience in Python and cloud-native systems.',
        'skills': 'Programming: Python, JavaScript; Web Technologies: React, Node.js; Databases: PostgreSQL; Tools & Platforms: Docker, Kubernetes, AWS',
        'experience': 'Senior Software Engineer | TechCorp Inc. | 2020 – Present\n- Built microservices in Python and Node.js on AWS.\n- Improved API latency by 30%.',
        'education': 'B.S. Computer Science | Stanford University | 2015 – 2019 | GPA: 3.8/4.0',
        'projects': 'E-Commerce Platform | React, Node.js, PostgreSQL\n- Implemented shopping cart and payment integration.',
        'certifications': 'AWS Certified Developer – Associate | 2023',
        'awards': 'Employee of the Year | TechCorp Inc. | 2024',
        'languages': 'English – Native, Hindi – Conversational',
        'linkedin': 'https://linkedin.com/in/johndoe',
        'github': 'https://github.com/johndoe',
        'website': 'https://johndoe.dev',
        'dob': '1995-08-15',
        'nationality': 'American',
        'softskills': 'Soft Skills: Communication, Teamwork, Problem-solving, Leadership',
        'career_objective': 'To contribute as a Senior Software Engineer in a high-impact product team, focusing on scalable backend systems and cloud infrastructure.',
        'photo_url': None
    }
    if template_name not in TEMPLATE_META:
        return "Template not found", 404
    return render_template(f'pdf/{template_name}.html', resume=dummy_resume)


# ========== SIMPLE UPLOAD (PDF/DOC/DOCX/PPT/PPTX) ==========
@app.route("/uploadpdf", methods=["POST"])
@login_required
def uploadpdf():
    # 1) Basic file checks
    if "pdffile" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("dashboard"))

    file = request.files["pdffile"]
    if not file.filename:
        flash("No file selected", "error")
        return redirect(url_for("dashboard"))

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".doc", ".docx", ".ppt", ".pptx"]:
        flash("Only PDF, DOC/DOCX, PPT/PPTX files are allowed", "error")
        return redirect(url_for("dashboard"))

    # 2) Save uploaded file
    filename = secure_filename(
        f"{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    )
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(upload_path)

    try:
        # 3) PARSE WITH YOUR TEMPLATE PARSER
        parsed = extractresumefrompdf(upload_path)

        # 4) Build a minimal dict just for ATS scoring
        parsed_for_ats = {
            "fullname":   parsed.get("fullname", ""),
            "email":      parsed.get("email", ""),
            "phone":      parsed.get("phone", ""),
            "location":   parsed.get("location", ""),
            "summary":    parsed.get("summary", ""),
            "skills":     parsed.get("skills", ""),
            "experience": parsed.get("experience", ""),
            "education":  parsed.get("education", ""),
            "projects":   parsed.get("projects", ""),
            "certifications": parsed.get("certifications", ""),
            "languages":  parsed.get("languages", ""),
            "keywords":   [],   # you can fill this later if you want
        }

        # 5) ATS scoring ONLY (do NOT replace content with optimized text)
        formatter = ATSFormatter()
        report = formatter.validate_ats_compliance(parsed_for_ats)

        # 6) Create Resume – DIRECT 1‑TO‑1 MAPPING INTO CORRECT FIELDS
        newresume = Resume(
            user_id=current_user.id,
            template_name="template1",

            # Header
            title=parsed.get("title") or "Imported Resume",
            fullname=parsed.get("fullname", ""),
            email=parsed.get("email", ""),
            phone=parsed.get("phone", ""),
            location=parsed.get("location", ""),

            # Main sections - each parser key → its own textbox
            summary=parsed.get("summary", ""),                  # PROFESSIONAL SUMMARY
            career_objective=parsed.get("careerobjective", ""), # CAREER OBJECTIVE
            skills=parsed.get("skills", ""),                    # TECHNICAL / CORE SKILLS
            softskills=parsed.get("softskills", ""),            # SOFT SKILLS
            experience=parsed.get("experience", ""),            # EXPERIENCE
            education=parsed.get("education", ""),              # EDUCATION
            projects=parsed.get("projects", ""),                # KEY PROJECTS
            certifications=parsed.get("certifications", ""),    # CERTIFICATIONS
            awards=parsed.get("awards", ""),                    # AWARDS (if any)
            languages=parsed.get("languages", ""),              # LANGUAGES

            # Links
            linkedin=parsed.get("linkedin", ""),
            github=parsed.get("github", ""),
            website=parsed.get("website", ""),

            # Extra personal details
            dob=parsed.get("dob", ""),
            nationality=parsed.get("nationality", ""),

            # ATS info
            ats_compliance_score=report["score"],
            ats_issues="\n".join(report["issues"]),
            ats_recommendations="\n".join(report["recommendations"]),
        )

        db.session.add(newresume)
        db.session.commit()

        flash(
            f"Resume imported! Name: {newresume.fullname or 'N/A'} | "
            f"Email: {newresume.email or 'N/A'} | ATS: {report['score']}/100",
            "success",
        )
        return redirect(url_for("edit_resume", resume_id=newresume.id))

    except Exception as e:
        print("UPLOAD PARSE ERROR:", e)
        flash("Error processing resume file", "error")
        return redirect(url_for("dashboard"))



# ========== ATS SCORE PAGE ==========
@app.route("/ats-score", methods=["GET", "POST"])
@login_required
def ats_score():
    if request.method == "POST":
        file = request.files.get("pdffile")
        if not file or not file.filename:
            flash("Please upload a resume PDF", "error")
            return redirect(url_for("ats_score"))

        if not file.filename.lower().endswith(".pdf"):
            flash("Only PDF files are allowed", "error")
            return redirect(url_for("ats_score"))

        filename = secure_filename(
            f"{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        )
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(upload_path)

        extracted = extract_resume_from_pdf(upload_path)

        parsed = {
            "fullname":   (extracted.get("fullname") or "").strip(),
            "email":      (extracted.get("email") or "").strip(),
            "phone":      (extracted.get("phone") or "").strip(),
            "location":   (extracted.get("location") or "").strip(),
            "summary":    " ".join((extracted.get("summary") or "").split()),
            "skills":     normalize_skills(extracted.get("skills") or ""),
            "experience": normalize_block_section(extracted.get("experience") or ""),
            "education":  normalize_block_section(extracted.get("education") or ""),
            "projects":   normalize_block_section(extracted.get("projects") or ""),
            "certifications": normalize_block_section(extracted.get("certifications") or ""),
            "languages":  normalize_languages_spoken(extracted.get("languages") or ""),
            "keywords":   [],
        }

        formatter = ATSFormatter()
        report = formatter.validate_ats_compliance(parsed)

        return render_template(
            "ats_score.html",
            score=report["score"],
            issues=report["issues"],
            warnings=report.get("warnings", []),
            recommendations=report["recommendations"],
        )

    return render_template("ats_score.html", score=None)


@app.route('/fix-titles')
@login_required
def fix_titles():
    resumes = Resume.query.filter_by(user_id=current_user.id).all()
    count = 0
    for i, resume in enumerate(resumes, 1):
        if resume.title == 'My Resume':
            resume.title = f"My Resume #{i}"
            count += 1
    db.session.commit()
    flash(f'✅ Fixed {count} resumes! Titles now unique.', 'success')
    return redirect(url_for('dashboard'))


# ===================== INIT =====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(debug=True, use_reloader=False)
