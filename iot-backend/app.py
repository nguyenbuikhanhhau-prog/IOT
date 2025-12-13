from flask import Flask, jsonify, request, render_template, session
from datetime import timedelta
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import os, string, random, time
import sendgrid
from sendgrid.helpers.mail import Mail

# ===============================
# LOAD ENV
# ===============================
load_dotenv()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")

# ===============================
# FLASK INIT
# ===============================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "iot-secret-key")  # BẮT BUỘC
app.permanent_session_lifetime = timedelta(hours=2)
CORS(app)
bcrypt = Bcrypt(app)

# ===============================
# MOCK DATABASE
# ===============================
users = [
    {
        "id": 1,
        "email": "admin@iot.com",
        "password": bcrypt.generate_password_hash("admin").decode("utf-8")
    }
]

# ===============================
# HELPER FUNCTIONS
# ===============================
def generate_random_password(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def send_password_email(to_email, new_password):
    try:
        sg = sendgrid.SendGridAPIClient(SENDGRID_API_KEY)

        message = Mail(
            from_email=EMAIL_USER,
            to_emails=to_email,
            subject="Reset mật khẩu - IOT Platform",
            plain_text_content=f"""
Mật khẩu mới của bạn là: {new_password}

Vui lòng đăng nhập và đổi mật khẩu ngay sau khi vào hệ thống.
"""
        )

        response = sg.send(message)
        print("📧 SendGrid status:", response.status_code)

        return response.status_code == 202

    except Exception as e:
        print("❌ SendGrid error:", e)
        return False

# ===============================
# ROUTES
# ===============================
@app.route("/")
def index():
    if "user_id" in session:
        return render_template("index.html")
    return render_template("login.html")


@app.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if any(u["email"] == email for u in users):
        return jsonify({"success": False, "message": "Email đã tồn tại"}), 400

    users.append({
        "id": len(users) + 1,
        "email": email,
        "password": bcrypt.generate_password_hash(password).decode("utf-8")
    })

    return jsonify({"success": True, "message": "Đăng ký thành công"})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = next((u for u in users if u["email"] == email), None)

    if user and bcrypt.check_password_hash(user["password"], password):
        session.permanent = True
        session["user_id"] = user["id"]
        session["email"] = user["email"]

        return jsonify({"success": True})

    return jsonify({"success": False, "message": "Sai email hoặc mật khẩu"}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get("email")

    user = next((u for u in users if u["email"] == email), None)

    if user:
        new_password = generate_random_password()
        user["password"] = bcrypt.generate_password_hash(new_password).decode("utf-8")

        if send_password_email(email, new_password):
            return jsonify({
                "success": True,
                "message": "Mật khẩu mới đã được gửi về email"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Lỗi gửi email"
            }), 500

    # Không tiết lộ email có tồn tại hay không
    return jsonify({
        "success": True,
        "message": "Nếu email tồn tại, mật khẩu mới sẽ được gửi"
    })

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return jsonify({"success": False}), 403

    data = request.json
    old_pw = data.get("old_password")
    new_pw = data.get("new_password")

    user = next((u for u in users if u["id"] == session["user_id"]), None)

    if not bcrypt.check_password_hash(user["password"], old_pw):
        return jsonify({"success": False, "message": "Sai mật khẩu cũ"}), 400

    user["password"] = bcrypt.generate_password_hash(new_pw).decode("utf-8")
    return jsonify({"success": True})

@app.route("/api/user_status")
def user_status():
    if "user_id" in session:
        return jsonify({
            "logged_in": True,
            "email": session["email"]
        })
    return jsonify({"logged_in": False})

# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    print("🚀 Server running on port 5000")
    app.run(host="0.0.0.0", port=5000, debug=True) 


