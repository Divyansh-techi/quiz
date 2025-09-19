import os
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from google import genai
from google.genai.errors import ServerError

app = Flask(__name__)
app.secret_key = 'supersecretkey'

API_KEY = "AIzaSyCCCDB8Tuw65PSWl9AUydMDaZrGdSynTd4"
client = genai.Client(api_key=API_KEY)

# Simple cache
mcq_cache = {}

def generate_mcqs_from_gemini(skill):
    prompt = (
        f"Generate 10 multiple choice questions about {skill}. "
        "Each question should have 4 options labeled A, B, C, D. "
        "At the end of each question, specify the correct answer like this: answer: A."
        "\n\n"
        "Format:\n"
        "Q: question text\n"
        "A: option A text\n"
        "B: option B text\n"
        "C: option C text\n"
        "D: option D text\n"
        "answer: <correct option letter>\n"
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"parts": [{"text": prompt}]}]
    )
    text = response.text

    questions = []
    blocks = text.strip().split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n")]
        if len(lines) >= 6:
            question_text = lines[0][3:].strip() if lines[0].startswith("Q:") else lines[0]
            opts = {}
            for line in lines[1:5]:
                if len(line) > 3 and line[1] == ":":
                    value = line[3:].strip()
                    opts[line[0]] = value if value else "Option not provided"

            answer_line_candidates = [line for line in lines[5:] if 'answer' in line.lower()]
            if answer_line_candidates:
                answer_line = answer_line_candidates[0]
                parts = answer_line.split(":")
                answer = parts[1].strip().upper() if len(parts) > 1 else "A"
            else:
                answer = "A"

            if all(opts.get(opt, "") for opt in ("A", "B", "C", "D")):
                questions.append({
                    "question": question_text,
                    "A": opts.get("A", ""),
                    "B": opts.get("B", ""),
                    "C": opts.get("C", ""),
                    "D": opts.get("D", ""),
                    "answer": answer
                })
    return questions

def generate_mcqs_with_retry_and_cache(skill, retries=3, delay=5):
    if skill in mcq_cache:
        return mcq_cache[skill]

    for attempt in range(retries):
        try:
            questions = generate_mcqs_from_gemini(skill)
            mcq_cache[skill] = questions
            return questions
        except ServerError as e:
            status_code = None
            if hasattr(e, "status_code"):
                status_code = e.status_code
            elif hasattr(e, "response") and hasattr(e.response, "status_code"):
                status_code = e.response.status_code
            elif e.args and len(e.args) > 0:
                status_code = e.args[0]

            if status_code == 503:
                if attempt < retries - 1:
                    time.sleep(delay * (2 ** attempt))  # exponential backoff
                    continue
                else:
                    raise
            else:
                raise

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        student_name = request.form.get('student_name')
        student_email = request.form.get('student_email')
        student_roll = request.form.get('student_roll')
        skills = [s.strip() for s in request.form.get('skills', '').split(',') if s.strip()]

        if not student_name or not student_email or not student_roll:
            error = "Please fill all student details."
            return render_template('index.html', error=error)

        session['student'] = {'name': student_name, 'email': student_email, 'roll': student_roll}
        session['skills'] = skills
        session['questions'] = {}

        try:
            for skill in skills:
                questions = generate_mcqs_with_retry_and_cache(skill)
                session['questions'][skill] = questions
        except ServerError:
            error = "The AI service is currently overloaded. Please try again after some time."
            return render_template('index.html', error=error)

        return redirect(url_for('quiz'))

    return render_template('index.html')

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    if 'skills' not in session:
        return redirect(url_for('index'))

    skills = session['skills']
    questions = session['questions']

    if request.method == 'POST':
        user_answers = {}
        for skill in skills:
            user_answers[skill] = []
            for i in range(len(questions[skill])):
                user_answers[skill].append(request.form.get(f'{skill}_{i}', ''))
        session['answers'] = user_answers
        return redirect(url_for('results'))

    return render_template('quiz.html', skills=skills, questions=questions)

@app.route('/results')
def results():
    student = session.get('student')
    skills = session.get('skills', [])
    questions = session.get('questions', {})
    answers = session.get('answers', {})
    scores = {}

    for skill in skills:
        correct = 0
        total = len(questions[skill])
        for idx, q in enumerate(questions[skill]):
            if idx < len(answers.get(skill, [])) and answers[skill][idx] == q.get('answer'):
                correct += 1
        scores[skill] = {'correct': correct, 'total': total}

    return render_template('results.html', scores=scores, questions=questions, answers=answers, student=student)

if __name__ == '__main__':
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")
    app.run(debug=True)
