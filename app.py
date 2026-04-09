from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
import os
import re 
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.config['UPLOAD_FOLDER_VIDEOS'] = 'static/uploads/videos'
app.config['UPLOAD_FOLDER_PRODUCTS'] = 'static/uploads/products'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max
app.config['ALLOWED_VIDEO_EXTENSIONS'] = {'mp4', 'avi', 'mov', 'mkv'}
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'upskill_db'
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] != role:
                flash('Access denied', 'error')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        phone = request.form.get('phone', '')

        if not name or not email or not password or not role:
            flash('All fields are required', 'error')
            return redirect(url_for('signup'))

        if not re.match(EMAIL_REGEX, email):
            flash('Please enter a valid email address', 'error')
            return redirect(url_for('signup'))

        if role == 'instructor':
            if not phone or len(phone) != 10 or not phone.isdigit():
                flash('Instructors must provide a valid 10-digit phone number', 'error')
                return redirect(url_for('signup'))

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "INSERT INTO users (name, email, password, role, phone) VALUES (%s, %s, %s, %s, %s)",
                (name, email, hashed_password, role, phone)
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            session['email'] = user['email']

            cursor.close()
            conn.close()

            flash('Welcome to UPSKILL!', 'success')

            if role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif role == 'instructor':
                return redirect(url_for('instructor_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))

        except mysql.connector.IntegrityError:
            flash('Email already exists', 'error')
            return redirect(url_for('signup'))

        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
            return redirect(url_for('signup'))

    return render_template('signup.html')



@app.route('/login', methods=['GET', 'POST'])

def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            session['email'] = user['email']
            
            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'instructor':
                return redirect(url_for('instructor_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')
    
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('home'))

@app.route('/courses')
def courses():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.*, u.name as instructor_name, 
        (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) as enrollment_count
        FROM courses c
        JOIN users u ON c.instructor_id = u.id
        ORDER BY c.created_at DESC
    """)
    all_courses = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('courses.html', courses=all_courses)

@app.route('/course/<int:course_id>')
@login_required
def course_detail(course_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.*, u.name as instructor_name, u.email as instructor_email, u.phone as instructor_phone,
        (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) as enrollment_count
        FROM courses c
        JOIN users u ON c.instructor_id = u.id
        WHERE c.id = %s
    """, (course_id,))
    course = cursor.fetchone()
    
    if not course:
        cursor.close()
        conn.close()
        return render_template('404.html'), 404
    
    cursor.execute("SELECT * FROM lessons WHERE course_id = %s ORDER BY created_at", (course_id,))
    lessons = cursor.fetchall()
    
    is_enrolled = False
    if session.get('role') == 'student':
        cursor.execute("SELECT * FROM enrollments WHERE student_id = %s AND course_id = %s",
                      (session['user_id'], course_id))
        is_enrolled = cursor.fetchone() is not None
    
    is_owner = session.get('user_id') == course['instructor_id']
    
    cursor.close()
    conn.close()
    
    return render_template('course_detail.html', course=course, lessons=lessons, is_enrolled=is_enrolled, is_owner=is_owner)

@app.route('/enroll/<int:course_id>')
@login_required
@role_required('student')
def enroll(course_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM enrollments WHERE student_id = %s AND course_id = %s",
                  (session['user_id'], course_id))
    if cursor.fetchone():
        flash('You are already enrolled in this course', 'info')
    else:
        cursor.execute("INSERT INTO enrollments (student_id, course_id) VALUES (%s, %s)",
                      (session['user_id'], course_id))
        conn.commit()
        flash('Successfully enrolled in the course!', 'success')
    
    cursor.close()
    conn.close()
    return redirect(url_for('course_detail', course_id=course_id))

@app.route('/student/dashboard')
@role_required('student')
def student_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.*, u.name as instructor_name
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        JOIN users u ON c.instructor_id = u.id
        WHERE e.student_id = %s
        ORDER BY e.enrolled_at DESC
    """, (session['user_id'],))
    enrolled_courses = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('student_dashboard.html', 
                         enrolled_courses=enrolled_courses,
                         total_enrollments=len(enrolled_courses))

@app.route('/instructor/dashboard')
@role_required('instructor')
def instructor_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as count FROM courses WHERE instructor_id = %s", (session['user_id'],))
    courses_count = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT COUNT(DISTINCT e.student_id) as count
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        WHERE c.instructor_id = %s
    """, (session['user_id'],))
    students_count = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM lessons l
        JOIN courses c ON l.course_id = c.id
        WHERE c.instructor_id = %s
    """, (session['user_id'],))
    lessons_count = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM products
        WHERE instructor_id = %s
    """, (session['user_id'],))
    products_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT * FROM courses WHERE instructor_id = %s ORDER BY created_at DESC", (session['user_id'],))
    my_courses = cursor.fetchall()
    
    cursor.execute("SELECT * FROM products WHERE instructor_id = %s ORDER BY created_at DESC", (session['user_id'],))
    my_products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('instructor_dashboard.html',
                         courses_count=courses_count,
                         students_count=students_count,
                         lessons_count=lessons_count,
                         products_count=products_count,
                         my_courses=my_courses,
                         my_products=my_products)

@app.route('/instructor/upload_course', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def upload_course():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        custom_category = request.form.get('custom_category')
        
        if category == 'Other Course' and custom_category:
            category = custom_category
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO courses (instructor_id, title, description, category) VALUES (%s, %s, %s, %s)",
            (session['user_id'], title, description, category)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Course created successfully!', 'success')
        return redirect(url_for('instructor_dashboard'))
    
    categories = [
        'Mehendi Design', 'Aari Work', 'Bridal Makeup', 'Hair Styling',
        'Baking', 'Crochet', 'Painting', 'Handicrafts', 'Calligraphy',
        'Jewelry Making', 'Other Course'
    ]
    return render_template('upload_course.html', categories=categories)

@app.route('/instructor/edit_course/<int:course_id>', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def edit_course(course_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM courses WHERE id = %s AND instructor_id = %s", (course_id, session['user_id']))
    course = cursor.fetchone()
    
    if not course:
        cursor.close()
        conn.close()
        flash('Course not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        custom_category = request.form.get('custom_category')
        
        if category == 'Other Course' and custom_category:
            category = custom_category
        
        cursor.execute(
            "UPDATE courses SET title = %s, description = %s, category = %s WHERE id = %s",
            (title, description, category, course_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Course updated successfully!', 'success')
        return redirect(url_for('instructor_dashboard'))
    
    categories = [
        'Mehendi Design', 'Aari Work', 'Bridal Makeup', 'Hair Styling',
        'Baking', 'Crochet', 'Painting', 'Handicrafts', 'Calligraphy',
        'Jewelry Making', 'Other Course'
    ]
    
    cursor.close()
    conn.close()
    return render_template('edit_course.html', course=course, categories=categories)

@app.route('/instructor/delete_course/<int:course_id>')
@login_required
@role_required('instructor')
def instructor_delete_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM courses WHERE id = %s AND instructor_id = %s", (course_id, session['user_id']))
    course = cursor.fetchone()
    
    if not course:
        cursor.close()
        conn.close()
        flash('Course not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    cursor.execute("DELETE FROM lessons WHERE course_id = %s", (course_id,))
    cursor.execute("DELETE FROM enrollments WHERE course_id = %s", (course_id,))
    cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Course deleted successfully', 'success')
    return redirect(url_for('instructor_dashboard'))

@app.route('/instructor/upload_lesson/<int:course_id>', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def upload_lesson(course_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM courses WHERE id = %s AND instructor_id = %s", (course_id, session['user_id']))
    course = cursor.fetchone()
    
    if not course:
        cursor.close()
        conn.close()
        flash('Course not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        video = request.files.get('video')
        
        if video and allowed_file(video.filename, app.config['ALLOWED_VIDEO_EXTENSIONS']):
            filename = secure_filename(video.filename)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = f"{timestamp}_{filename}"
            video_path = os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], filename)
            video.save(video_path)
            
            cursor.execute(
                "INSERT INTO lessons (course_id, title, video_path) VALUES (%s, %s, %s)",
                (course_id, title, f"uploads/videos/{filename}")
            )
            conn.commit()
            flash('Lesson uploaded successfully!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('course_detail', course_id=course_id))
        else:
            flash('Invalid video file', 'error')
    
    cursor.close()
    conn.close()
    return render_template('upload_lesson.html', course=course)

@app.route('/instructor/edit_lesson/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def edit_lesson(lesson_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT l.*, c.instructor_id, c.title as course_title, c.id as course_id
        FROM lessons l
        JOIN courses c ON l.course_id = c.id
        WHERE l.id = %s AND c.instructor_id = %s
    """, (lesson_id, session['user_id']))
    lesson = cursor.fetchone()
    
    if not lesson:
        cursor.close()
        conn.close()
        flash('Lesson not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        video = request.files.get('video')
        
        if video and allowed_file(video.filename, app.config['ALLOWED_VIDEO_EXTENSIONS']):
            filename = secure_filename(video.filename)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = f"{timestamp}_{filename}"
            video_path = os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], filename)
            video.save(video_path)
            
            cursor.execute(
                "UPDATE lessons SET title = %s, video_path = %s WHERE id = %s",
                (title, f"uploads/videos/{filename}", lesson_id)
            )
        else:
            cursor.execute("UPDATE lessons SET title = %s WHERE id = %s", (title, lesson_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lesson updated successfully!', 'success')
        return redirect(url_for('course_detail', course_id=lesson['course_id']))
    
    cursor.close()
    conn.close()
    return render_template('edit_lesson.html', lesson=lesson)

@app.route('/instructor/delete_lesson/<int:lesson_id>')
@login_required
@role_required('instructor')
def delete_lesson(lesson_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT l.*, c.instructor_id, c.id as course_id
        FROM lessons l
        JOIN courses c ON l.course_id = c.id
        WHERE l.id = %s AND c.instructor_id = %s
    """, (lesson_id, session['user_id']))
    lesson = cursor.fetchone()
    
    if not lesson:
        cursor.close()
        conn.close()
        flash('Lesson not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    cursor.execute("DELETE FROM lessons WHERE id = %s", (lesson_id,))
    conn.commit()
    
    course_id = lesson['course_id']
    cursor.close()
    conn.close()
    
    flash('Lesson deleted successfully', 'success')
    return redirect(url_for('course_detail', course_id=course_id))

@app.route('/products')
def products():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.*, u.name as seller_name,
        (SELECT image_path FROM product_images WHERE product_id = p.id LIMIT 1) as first_image
        FROM products p
        JOIN users u ON p.instructor_id = u.id
        ORDER BY p.created_at DESC
    """)
    all_products = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('products.html', products=all_products)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.*, u.name as seller_name
        FROM products p
        JOIN users u ON p.instructor_id = u.id
        WHERE p.id = %s
    """, (product_id,))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        conn.close()
        return render_template('404.html'), 404
    
    cursor.execute("SELECT * FROM product_images WHERE product_id = %s", (product_id,))
    images = cursor.fetchall()
    
    is_owner = session.get('user_id') == product['instructor_id']
    
    cursor.close()
    conn.close()
    
    return render_template('product_detail.html', product=product, images=images, is_owner=is_owner)

@app.route('/instructor/upload_product', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def upload_product():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        custom_category = request.form.get('custom_category')
        price = request.form.get('price')
        contact_email = request.form.get('contact_email')
        contact_phone = request.form.get('contact_phone')
        
        if not contact_phone or len(contact_phone) != 10 or not contact_phone.isdigit():
            flash('Please provide a valid 10-digit phone number', 'error')
            return redirect(url_for('upload_product'))
        
        if category == 'Other Course' and custom_category:
            category = custom_category
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO products (instructor_id, name, description, category, price, contact_email, contact_phone) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (session['user_id'], name, description, category, price, contact_email, contact_phone)
        )
        product_id = cursor.lastrowid
        
        images = request.files.getlist('images')
        for image in images:
            if image and allowed_file(image.filename, app.config['ALLOWED_IMAGE_EXTENSIONS']):
                filename = secure_filename(image.filename)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"{timestamp}_{filename}"
                image_path = os.path.join(app.config['UPLOAD_FOLDER_PRODUCTS'], filename)
                image.save(image_path)
                
                cursor.execute(
                    "INSERT INTO product_images (product_id, image_path) VALUES (%s, %s)",
                    (product_id, f"uploads/products/{filename}")
                )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Product uploaded successfully!', 'success')
        return redirect(url_for('instructor_dashboard'))
    
    categories = [
        'Mehendi Design', 'Aari Work', 'Bridal Makeup', 'Hair Styling',
        'Baking', 'Crochet', 'Painting', 'Handicrafts', 'Calligraphy',
        'Jewelry Making', 'Other Course'
    ]
    return render_template('upload_product.html', categories=categories)

@app.route('/instructor/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def edit_product(product_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM products WHERE id = %s AND instructor_id = %s", (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        conn.close()
        flash('Product not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        custom_category = request.form.get('custom_category')
        price = request.form.get('price')
        contact_email = request.form.get('contact_email')
        contact_phone = request.form.get('contact_phone')
        
        if not contact_phone or len(contact_phone) != 10 or not contact_phone.isdigit():
            flash('Please provide a valid 10-digit phone number', 'error')
            return redirect(url_for('edit_product', product_id=product_id))
        
        if category == 'Other Course' and custom_category:
            category = custom_category
        
        cursor.execute(
            "UPDATE products SET name = %s, description = %s, category = %s, price = %s, contact_email = %s, contact_phone = %s WHERE id = %s",
            (name, description, category, price, contact_email, contact_phone, product_id)
        )
        
        images = request.files.getlist('images')
        if images and images[0].filename:
            for image in images:
                if image and allowed_file(image.filename, app.config['ALLOWED_IMAGE_EXTENSIONS']):
                    filename = secure_filename(image.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    image_path = os.path.join(app.config['UPLOAD_FOLDER_PRODUCTS'], filename)
                    image.save(image_path)
                    
                    cursor.execute(
                        "INSERT INTO product_images (product_id, image_path) VALUES (%s, %s)",
                        (product_id, f"uploads/products/{filename}")
                    )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Product updated successfully!', 'success')
        return redirect(url_for('instructor_dashboard'))
    
    cursor.execute("SELECT * FROM product_images WHERE product_id = %s", (product_id,))
    images = cursor.fetchall()
    
    categories = [
        'Mehendi Design', 'Aari Work', 'Bridal Makeup', 'Hair Styling',
        'Baking', 'Crochet', 'Painting', 'Handicrafts', 'Calligraphy',
        'Jewelry Making', 'Other Course'
    ]
    
    cursor.close()
    conn.close()
    return render_template('edit_product.html', product=product, images=images, categories=categories)

@app.route('/instructor/delete_product/<int:product_id>')
@login_required
@role_required('instructor')
def instructor_delete_product(product_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM products WHERE id = %s AND instructor_id = %s", (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        conn.close()
        flash('Product not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    cursor.execute("DELETE FROM product_images WHERE product_id = %s", (product_id,))
    cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Product deleted successfully', 'success')
    return redirect(url_for('instructor_dashboard'))

@app.route('/instructor/delete_product_image/<int:image_id>/<int:product_id>')
@login_required
@role_required('instructor')
def delete_product_image(image_id, product_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT pi.* FROM product_images pi
        JOIN products p ON pi.product_id = p.id
        WHERE pi.id = %s AND p.instructor_id = %s
    """, (image_id, session['user_id']))
    
    image = cursor.fetchone()
    
    if not image:
        cursor.close()
        conn.close()
        flash('Image not found or access denied', 'error')
        return redirect(url_for('instructor_dashboard'))
    
    cursor.execute("DELETE FROM product_images WHERE id = %s", (image_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Image deleted successfully', 'success')
    return redirect(url_for('edit_product', product_id=product_id))

@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student'")
    students_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'instructor'")
    instructors_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM courses")
    courses_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM lessons")
    lessons_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM enrollments")
    enrollments_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM products")
    products_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 10")
    recent_users = cursor.fetchall()
    
    cursor.execute("""
        SELECT c.*, u.name as instructor_name
        FROM courses c
        JOIN users u ON c.instructor_id = u.id
        ORDER BY c.created_at DESC LIMIT 10
    """)
    recent_courses = cursor.fetchall()
    
    cursor.execute("""
        SELECT e.*, u.name as student_name, c.title as course_title
        FROM enrollments e
        JOIN users u ON e.student_id = u.id
        JOIN courses c ON e.course_id = c.id
        ORDER BY e.enrolled_at DESC LIMIT 10
    """)
    recent_enrollments = cursor.fetchall()
    
    cursor.execute("""
        SELECT p.*, u.name as seller_name
        FROM products p
        JOIN users u ON p.instructor_id = u.id
        ORDER BY p.created_at DESC LIMIT 10
    """)
    recent_products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('admin.html',
                         students_count=students_count,
                         instructors_count=instructors_count,
                         courses_count=courses_count,
                         lessons_count=lessons_count,
                         enrollments_count=enrollments_count,
                         products_count=products_count,
                         recent_users=recent_users,
                         recent_courses=recent_courses,
                         recent_enrollments=recent_enrollments,
                         recent_products=recent_products)

@app.route('/admin/delete_course/<int:course_id>')
@login_required
@role_required('admin')
def delete_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lessons WHERE course_id = %s", (course_id,))
    cursor.execute("DELETE FROM enrollments WHERE course_id = %s", (course_id,))
    cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Course deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_product/<int:product_id>')
@login_required
@role_required('admin')
def delete_product(product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM product_images WHERE product_id = %s", (product_id,))
    cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Product deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER_VIDEOS'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_PRODUCTS'], exist_ok=True)
    app.run(debug=True)