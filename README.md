
# Project Title

A brief description of what this project does and who it's for
Smart Resume Builder 🚀
ATS-aware Flask web app that parses PDFs/DOCX/PPT resumes, extracts structured data, optimizes for ATS compliance, and generates modern, printable resume templates.

✨ Features
Feature	Description
📄 Smart Parsing	Upload PDF/DOCX/PPT → extracts name, contact, skills, experience, education, projects
🎯 ATS Scoring	Analyzes compliance (0-100), suggests improvements, highlights missing keywords
📱 Multi-Template	10+ modern HTML/CSS templates → A4-ready PDF export
⚡ Job Matching	Compares resume vs job description, shows alignment gaps
✏️ Live Editing	Pre-filled forms for all sections (career objective, summary, soft skills, etc.)
🛠️ Tech Stack
text
Backend: Flask, Python 3.11, Flask-SQLAlchemy, Flask-Login
Parsing: pdfplumber, python-docx, python-pptx
ATS Engine: Custom ATSResumeEnhancer + ATSFormatter + ats_normalizer
Frontend: HTML5/CSS3, Bootstrap 5, Jinja2 templates
Database: SQLite (PostgreSQL ready)
Deployment: Heroku/Render/Vercel ready
🚀 Quick Start
bash
# Clone repo
git clone https://github.com/yourusername/smart-resume-builder.git
cd smart-resume-builder

# Virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate    # Windows

# Install
pip install -r requirements.txt

# Run
python app.py
Open: http://localhost:5000

📁 Structure
text
smart-resume-builder/
├── app.py                 # Main Flask app
├── services/
│   ├── text_extractor.py  # PDF/DOCX/PPT parser (14+ templates)
│   ├── atsresumeenhancer.py # ATS analysis engine
│   ├── atsformatter.py    # ATS scoring + optimization
│   └── ats_normalizer.py  # Content cleaning
├── templates/             # 10+ resume templates
├── static/                # CSS/JS assets
├── uploads/               # User resume uploads
└── requirements.txt
🎯 Usage Flow
text
1. Upload resume (PDF/DOCX/PPT)
2. Auto-parse → ATS Score (85/100) → Edit form
3. Customize → Choose template → Download PDF
📈 ATS Scoring
Score	Status	Action
85-100	✅ Excellent	Ready to apply
70-84	🟡 Good	Minor tweaks
50-69	🟠 Average	Optimize keywords
0-49	🔴 Weak	Major improvements

🤝 Contributing
Fork repo

git checkout -b feature/new-feature

Commit: git commit -m "Add new feature"

Push: git push origin feature/new-feature

Open PR
