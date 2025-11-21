from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db_connection, DATABASE
import sqlite3
import os
from functools import wraps
from datetime import datetime, timedelta, date, time as time_obj 

# --- App Setup ---
# Check and initialize database on app startup if it doesn't exist
if not os.path.exists(DATABASE):
    print("Database not found. Initializing database...")
    init_db()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default_dev_secret_key_hms_123') 

# --- Database Connection and Cleanup ---

def get_db():
    """Helper to get DB connection on request and store it in the application context."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = get_db_connection()
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes DB connection after request is complete."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Authentication and Authorization Decorator ---

def login_required(role=None):
    """Decorator to enforce login and optional role-based access."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            if role and session.get('role') != role:
                flash('Access denied: Insufficient privileges.', 'danger')
                if session['role'] == 'Admin':
                    return redirect(url_for('admin_dashboard'))
                if session['role'] == 'Doctor':
                    return redirect(url_for('doctor_dashboard'))
                if session['role'] == 'Patient':
                    return redirect(url_for('patient_dashboard'))
                return redirect(url_for('index'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

# --- Common Routes ---

@app.route('/')
def index():
    if 'user_id' in session:
        role = session['role']
        if role == 'Admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'Doctor':
            return redirect(url_for('doctor_dashboard'))
        elif role == 'Patient':
            return redirect(url_for('patient_dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM user WHERE username = ? AND is_active = 1', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear() 
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['name'] = user['name']
            flash(f"Welcome back, {user['name']}!", 'success')
            if user['role'] == 'Admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'Doctor':
                return redirect(url_for('doctor_dashboard'))
            elif user['role'] == 'Patient':
                return redirect(url_for('patient_dashboard'))
        else:
            flash('Invalid username or password, or your account is inactive.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles patient registration only."""
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        password_hash = generate_password_hash(password)
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute('''
                INSERT INTO user (username, password_hash, role, name)
                VALUES (?, ?, ?, ?)
            ''', (username, password_hash, 'Patient', name))
            user_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO patient (patient_id)
                VALUES (?)
            ''', (user_id,))
            db.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists. Please choose a different one.', 'danger')
        except Exception as e:
            db.rollback()
            flash(f'An unexpected error occurred during registration: {e}', 'danger')
    return render_template('register.html')

@app.route('/logout')
def logout():
    """Clears the session and logs the user out."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# =========================================================================
# --- ADMIN ROUTES ---
# =========================================================================

@app.route('/admin/dashboard', methods=['GET'])
@login_required(role='Admin')
def admin_dashboard():
    db = get_db()
    
    # 1. Core Statistics
    stats = db.execute('''
        SELECT 
            (SELECT COUNT(*) FROM user WHERE role='Doctor' AND is_active = 1) AS active_doctors,
            (SELECT COUNT(*) FROM user WHERE role='Patient' AND is_active = 1) AS active_patients,
            (SELECT COUNT(*) FROM appointment WHERE status = 'Booked') AS upcoming_appointments,
            (SELECT COUNT(*) FROM appointment) AS total_appointments
    ''').fetchone()
    
    # 2. Registered Doctors
    doctors = db.execute('''
        SELECT u.user_id, u.name, d.specialization_name, u.is_active
        FROM user u
        LEFT JOIN doctor d ON u.user_id = d.doctor_id
        WHERE u.role = 'Doctor'
        ORDER BY u.name
    ''').fetchall()

    # 3. Registered Patients
    patients = db.execute('''
        SELECT user_id, name, contact_info, is_active
        FROM user 
        WHERE role = 'Patient'
        ORDER BY name
    ''').fetchall()

    # 4. Upcoming Appointments (Limited view)
    upcoming_appointments = db.execute('''
        SELECT 
            a.app_id, 
            p_user.name AS patient_name, 
            d_user.name AS doctor_name,
            dept.name AS department_name
        FROM appointment a
        JOIN user p_user ON a.patient_id = p_user.user_id
        JOIN user d_user ON a.doctor_id = d_user.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        JOIN department dept ON d.dept_id = dept.dept_id
        WHERE a.status = 'Booked'
        ORDER BY a.date, a.time
        LIMIT 10 
    ''').fetchall()

    # 5. All departments (for the Add Doctor Form)
    departments = db.execute('SELECT dept_id, name FROM department ORDER BY name').fetchall()
    
    return render_template('admin/dashboard.html', 
                           stats=stats, 
                           doctors=doctors,
                           patients=patients,
                           appointments=upcoming_appointments,
                           departments=departments)


@app.route('/admin/doctor/add', methods=['GET', 'POST'])
@login_required(role='Admin')
def add_doctor():
    """Handles displaying the form (GET) and submitting new doctor data (POST)."""
    db = get_db()
    
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        dept_id = request.form['dept_id']
        contact_info = request.form.get('contact_info')
        
        cursor = db.cursor()
        password_hash = generate_password_hash(password)

        try:
            # 1. Find the specialization name
            dept = db.execute('SELECT name FROM department WHERE dept_id = ?', (dept_id,)).fetchone()
            if not dept:
                flash('Invalid Department selected.', 'danger')
                departments = db.execute('SELECT dept_id, name FROM department ORDER BY name').fetchall()
                return render_template('admin/add_doctor.html', departments=departments) 

            specialization_name = dept['name']

            # 2. Insert into User table
            cursor.execute('''
                INSERT INTO user (username, password_hash, role, name, contact_info)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, password_hash, 'Doctor', name, contact_info))
            doctor_id = cursor.lastrowid
            
            # 3. Insert into Doctor table
            cursor.execute('''
                INSERT INTO doctor (doctor_id, dept_id, specialization_name)
                VALUES (?, ?, ?)
            ''', (doctor_id, dept_id, specialization_name))
            
            db.commit()
            flash(f'Doctor {name} added successfully! Login: {username} / {password}', 'success')
            return redirect(url_for('admin_dashboard'))

        except sqlite3.IntegrityError:
            flash('Username already exists. Please choose a different one.', 'danger')
        except Exception as e:
            db.rollback()
            flash(f'An unexpected error occurred: {e}', 'danger')
        
        departments = db.execute('SELECT dept_id, name FROM department ORDER BY name').fetchall()
        return render_template('admin/add_doctor.html', departments=departments)
        
    # GET request: Display the form
    departments = db.execute('SELECT dept_id, name FROM department ORDER BY name').fetchall()
    return render_template('admin/add_doctor.html', departments=departments)


@app.route('/admin/toggle_user_status/<int:user_id>/<string:action>', methods=['POST'])
@login_required(role='Admin')
def toggle_user_status(user_id, action):
    """Handles blacklisting/deleting (setting is_active=0) or activating (is_active=1) users."""
    db = get_db()
    
    if action == 'blacklist' or action == 'delete':
        new_status = 0
        status_word = 'Blacklisted'
        flash_category = 'warning'
    elif action == 'activate':
        new_status = 1
        status_word = 'Activated'
        flash_category = 'success'
    else:
        flash('Invalid action requested.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        # Prevent Admin from blacklisting themselves
        if user_id == session['user_id']:
            flash('You cannot change your own status.', 'danger')
            return redirect(url_for('admin_dashboard'))
            
        cursor = db.cursor()
        cursor.execute('''
            UPDATE user SET is_active = ? WHERE user_id = ?
        ''', (new_status, user_id))
        
        db.commit()
        
        user = db.execute('SELECT name, role FROM user WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            flash(f"{user['role']} '{user['name']}' has been {status_word}!", flash_category)
        else:
            flash(f"User ID {user_id} status updated to {status_word}.", flash_category)

    except Exception as e:
        db.rollback()
        flash(f'Database error during status update: {e}', 'danger')

    return redirect(url_for('admin_dashboard'))


# =========================================================================
# --- DOCTOR ROUTES ---
# =========================================================================

@app.route('/doctor/dashboard')
@login_required(role='Doctor')
def doctor_dashboard():
    doctor_id = session['user_id']
    db = get_db()
    
    today = date.today().strftime('%Y-%m-%d')

    # 1. Fetch upcoming booked appointments
    appointments = db.execute('''
        SELECT a.app_id, a.date, a.time, u.name AS patient_name, u.user_id AS patient_id
        FROM appointment a
        JOIN user u ON a.patient_id = u.user_id
        WHERE a.doctor_id = ? 
          AND a.status = 'Booked'
          AND a.date >= ?
        ORDER BY a.date, a.time
    ''', (doctor_id, today)).fetchall()

    # 2. Fetch all unique assigned patients for the 'Assigned Patients' list
    assigned_patients = db.execute('''
        SELECT DISTINCT u.user_id AS patient_id, u.name AS patient_name
        FROM appointment a
        JOIN user u ON a.patient_id = u.user_id
        WHERE a.doctor_id = ?
        ORDER BY u.name
    ''', (doctor_id,)).fetchall()
    
    return render_template('doctor/dashboard.html', 
                           appointments=appointments,
                           assigned_patients=assigned_patients)


@app.route('/doctor/availability', methods=['GET', 'POST'])
@login_required(role='Doctor')
def set_doctor_availability():
    doctor_id = session['user_id']
    db = get_db()
    
    future_dates = [(date.today() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 8)]
    
    if request.method == 'POST':
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM doctor_availability 
                WHERE doctor_id = ? AND date IN ({})
            '''.format(','.join(['?'] * len(future_dates))), 
            (doctor_id, *future_dates))

            slots = {
                'morning': ('08:00', '12:00'),
                'evening': ('16:00', '20:00')
            }

            for date_str in future_dates:
                for slot_key, (start_time, end_time) in slots.items():
                    if request.form.get(f'{date_str}_{slot_key}'):
                        cursor.execute('''
                            INSERT INTO doctor_availability (doctor_id, date, start_time, end_time)
                            VALUES (?, ?, ?, ?)
                        ''', (doctor_id, date_str, start_time, end_time))
            
            conn.commit()
            flash('Availability updated successfully for the next 7 days!', 'success')
            return redirect(url_for('doctor_dashboard'))
            
        except Exception as e:
            conn.rollback()
            flash(f'An error occurred while updating availability: {e}', 'danger')
            return redirect(url_for('set_doctor_availability'))

    # GET request: Display current availability
    availability = db.execute('''
        SELECT date, start_time, end_time FROM doctor_availability
        WHERE doctor_id = ? AND date IN ({})
        ORDER BY date, start_time
    '''.format(','.join(['?'] * len(future_dates))), 
    (doctor_id, *future_dates)).fetchall()
    
    availability_map = {}
    for row in availability:
        if row['date'] not in availability_map:
            availability_map[row['date']] = []
        availability_map[row['date']].append(row['start_time'])

    return render_template('doctor/set_availability.html', 
                           future_dates=future_dates, 
                           availability_map=availability_map)


@app.route('/doctor/patient_history/<int:patient_id>')
@login_required(role='Doctor')
def doctor_view_patient_history(patient_id):
    doctor_id = session['user_id']
    db = get_db()
    
    # 1. Fetch patient details and ensure the doctor is assigned to this patient (via appointments)
    patient_info = db.execute('''
        SELECT u.name, d.name AS doctor_name, dept.name AS department_name
        FROM user u
        JOIN appointment a ON u.user_id = a.patient_id
        JOIN user d ON a.doctor_id = d.user_id
        JOIN doctor dr ON d.user_id = dr.doctor_id
        JOIN department dept ON dr.dept_id = dept.dept_id
        WHERE u.user_id = ? AND a.doctor_id = ?
        LIMIT 1
    ''', (patient_id, doctor_id)).fetchone()

    if not patient_info:
        flash("Patient not found or you are not authorized to view this patient's history.", 'danger')
        return redirect(url_for('doctor_dashboard'))

    # 2. Fetch all completed treatments for this patient
    history = db.execute('''
        SELECT 
            a.app_id, 
            a.date, 
            t.diagnosis, 
            t.prescription, 
            t.notes
        FROM appointment a
        JOIN treatment t ON a.app_id = t.app_id
        WHERE a.patient_id = ? AND a.doctor_id = ? 
        ORDER BY a.date DESC
    ''', (patient_id, doctor_id)).fetchall()

    return render_template('doctor/patient_history.html', 
                           patient_info=patient_info, 
                           history=history)


@app.route('/doctor/update_treatment/<int:app_id>', methods=['GET', 'POST'])
@login_required(role='Doctor')
def update_treatment(app_id):
    doctor_id = session['user_id']
    db = get_db()

    # 1. Verify and fetch appointment details
    appt = db.execute('''
        SELECT a.patient_id, u.name AS patient_name
        FROM appointment a
        JOIN user u ON a.patient_id = u.user_id
        WHERE a.app_id = ? AND a.doctor_id = ?
    ''', (app_id, doctor_id)).fetchone()

    if not appt:
        flash("Appointment not found or you are not authorized to update it.", 'danger')
        return redirect(url_for('doctor_dashboard'))

    patient_name = appt['patient_name']
    
    if request.method == 'POST':
        diagnosis = request.form['diagnosis']
        prescription = request.form['prescription']
        notes = request.form.get('notes')
        
        try:
            conn = get_db()
            cursor = conn.cursor()

            # 2. Insert treatment record (ensures only one treatment per appointment via UNIQUE constraint)
            cursor.execute('''
                INSERT INTO treatment (app_id, diagnosis, prescription, notes)
                VALUES (?, ?, ?, ?)
            ''', (app_id, diagnosis, prescription, notes))

            # 3. Update appointment status to Completed
            cursor.execute('''
                UPDATE appointment SET status = 'Completed' WHERE app_id = ?
            ''', (app_id,))
            
            conn.commit()
            flash(f"Treatment recorded and appointment {app_id} marked as COMPLETED for {patient_name}.", 'success')
            return redirect(url_for('doctor_dashboard'))

        except sqlite3.IntegrityError:
            flash("Error: Treatment already exists for this appointment.", 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'Database error: {e}', 'danger')

    # GET request (or POST failure)
    return render_template('doctor/update_treatment.html', 
                           app_id=app_id, 
                           patient_name=patient_name)

@app.route('/doctor/cancel_appointment/<int:app_id>', methods=['POST'])
@login_required(role='Doctor')
def doctor_cancel_appointment(app_id):
    doctor_id = session['user_id']
    db = get_db()
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE appointment SET status = 'Cancelled' 
            WHERE app_id = ? AND doctor_id = ? AND status = 'Booked'
        ''', (app_id, doctor_id))
        
        if cursor.rowcount == 0:
            flash("Appointment not found, already completed, or you lack authorization.", 'warning')
        else:
            conn.commit()
            flash(f"Appointment {app_id} successfully cancelled.", 'info')

    except Exception as e:
        conn.rollback()
        flash(f'Database error during cancellation: {e}', 'danger')
        
    return redirect(url_for('doctor_dashboard'))


# =========================================================================
# --- PATIENT ROUTES ---
# =========================================================================

@app.route('/patient/dashboard')
@login_required(role='Patient')
def patient_dashboard():
    patient_id = session['user_id']
    db = get_db()
    
    # 1. Fetch all departments for browsing/searching
    departments = db.execute('SELECT * FROM department ORDER BY name').fetchall()
    
    # 2. Fetch upcoming appointments
    upcoming_appointments = db.execute('''
        SELECT a.app_id, a.date, a.time, u.name AS doctor_name, d.specialization_name, a.status
        FROM appointment a
        JOIN user u ON a.doctor_id = u.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        WHERE a.patient_id = ? AND a.status = 'Booked'
        ORDER BY a.date, a.time
    ''', (patient_id,)).fetchall()
    
    # 3. Fetch past appointments for history
    past_appointments = db.execute('''
        SELECT a.app_id, a.date, u.name AS doctor_name, d.specialization_name, t.diagnosis, t.prescription
        FROM appointment a
        JOIN user u ON a.doctor_id = u.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        LEFT JOIN treatment t ON a.app_id = t.app_id
        WHERE a.patient_id = ? AND a.status = 'Completed'
        ORDER BY a.date DESC
    ''', (patient_id,)).fetchall()

    return render_template('patient/dashboard.html', 
                           departments=departments, 
                           upcoming_appointments=upcoming_appointments,
                           past_appointments=past_appointments)

@app.route('/patient/department/<int:dept_id>')
@login_required(role='Patient')
def view_department(dept_id):
    db = get_db()
    
    department = db.execute('SELECT * FROM department WHERE dept_id = ?', (dept_id,)).fetchone()
    if not department:
        flash("Department not found.", 'danger')
        return redirect(url_for('patient_dashboard'))

    doctors = db.execute('''
        SELECT u.user_id, u.name, u.contact_info, d.specialization_name
        FROM user u
        JOIN doctor d ON u.user_id = d.doctor_id
        WHERE d.dept_id = ? AND u.is_active = 1
        ORDER BY u.name
    ''', (dept_id,)).fetchall()

    return render_template('patient/department_view.html', 
                           department=department, 
                           doctors=doctors)

@app.route('/patient/doctor/<int:doctor_id>')
@login_required(role='Patient')
def view_doctor_profile(doctor_id):
    db = get_db()
    
    doctor = db.execute('''
        SELECT 
            u.name, u.contact_info, d.specialization_name, dept.description AS dept_description
            , 'MBBS, MD - ' || d.specialization_name AS degrees, 
            '15 Years' AS experience_overall
        FROM user u
        JOIN doctor d ON u.user_id = d.doctor_id
        JOIN department dept ON d.dept_id = dept.dept_id
        WHERE u.user_id = ? AND u.role = 'Doctor' AND u.is_active = 1
    ''', (doctor_id,)).fetchone()

    if not doctor:
        flash("Doctor profile not found.", 'danger')
        return redirect(url_for('patient_dashboard'))

    return render_template('patient/doctor_profile.html', doctor=doctor, doctor_id=doctor_id)


@app.route('/patient/check_availability/<int:doctor_id>')
@login_required(role='Patient')
def check_doctor_availability(doctor_id):
    db = get_db()
    
    doctor_name = db.execute('SELECT name FROM user WHERE user_id = ?', (doctor_id,)).fetchone()
    if not doctor_name:
        flash("Doctor not found.", 'danger')
        return redirect(url_for('patient_dashboard'))
    
    future_dates = [(date.today() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 8)]

    # 1. Fetch Doctor's set available slots
    availability = db.execute('''
        SELECT date, start_time, end_time FROM doctor_availability
        WHERE doctor_id = ? AND date IN ({})
        ORDER BY date, start_time
    '''.format(','.join(['?'] * len(future_dates))), 
    (doctor_id, *future_dates)).fetchall()
    
    # 2. Fetch currently booked slots for the same period
    booked_slots = db.execute('''
        SELECT date, time FROM appointment
        WHERE doctor_id = ? AND date IN ({}) AND status = 'Booked'
    '''.format(','.join(['?'] * len(future_dates))), 
    (doctor_id, *future_dates)).fetchall()
    
    booked_map = {(row['date'], row['time']): True for row in booked_slots}

    # 3. Process Availability to create final slots (30-minute slots)
    available_slots = {}
    slot_duration = 30 

    for avail_row in availability:
        avail_date = avail_row['date']
        start_dt = datetime.strptime(avail_date + " " + avail_row['start_time'], '%Y-%m-%d %H:%M')
        end_dt_limit = datetime.strptime(avail_date + " " + avail_row['end_time'], '%Y-%m-%d %H:%M')
        
        current_dt = start_dt
        
        while current_dt < end_dt_limit:
            slot_time = current_dt.strftime('%H:%M')
            slot_end_time = (current_dt + timedelta(minutes=slot_duration)).strftime('%H:%M') 
            
            is_booked = booked_map.get((avail_date, slot_time), False)
            
            if avail_date not in available_slots:
                available_slots[avail_date] = []
            
            available_slots[avail_date].append({
                'time': slot_time,
                'end_time': slot_end_time,
                'is_booked': is_booked
            })
            
            current_dt += timedelta(minutes=slot_duration)

    return render_template('patient/doctor_availability.html', 
                           doctor_id=doctor_id,
                           doctor_name=doctor_name['name'],
                           available_slots=available_slots)


@app.route('/patient/book_slot/<int:doctor_id>/<string:date_str>/<string:time_str>', methods=['POST'])
@login_required(role='Patient')
def book_appointment(doctor_id, date_str, time_str):
    patient_id = session['user_id']
    
    try:
        appt_datetime = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        if appt_datetime < datetime.now():
            flash("Cannot book an appointment in the past.", 'danger')
            return redirect(url_for('patient_dashboard'))
    except ValueError:
        flash("Invalid date or time format.", 'danger')
        return redirect(url_for('patient_dashboard'))
    
    db = get_db()
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Concurrency check: is the slot still free?
        is_booked = cursor.execute('''
            SELECT app_id FROM appointment 
            WHERE doctor_id = ? AND date = ? AND time = ? AND status = 'Booked'
        ''', (doctor_id, date_str, time_str)).fetchone()
        
        if is_booked:
            flash("This slot was just booked by another patient. Please select a different time.", 'danger')
            return redirect(url_for('check_doctor_availability', doctor_id=doctor_id))

        # 2. Book the slot
        cursor.execute('''
            INSERT INTO appointment (patient_id, doctor_id, date, time, status)
            VALUES (?, ?, ?, ?, 'Booked')
        ''', (patient_id, doctor_id, date_str, time_str))
        
        conn.commit()
        
        doctor_name = db.execute('SELECT name FROM user WHERE user_id = ?', (doctor_id,)).fetchone()['name']
        flash(f"Appointment booked successfully with Dr. {doctor_name} on {date_str} at {time_str}.", 'success')
        
    except sqlite3.IntegrityError:
        flash("Integrity Error: Double-booking attempted. Please check your dashboard.", 'danger')
    except Exception as e:
        conn.rollback()
        flash(f"An unexpected error occurred during booking: {e}", 'danger')
        
    return redirect(url_for('patient_dashboard'))

@app.route('/patient/cancel_appointment/<int:app_id>', methods=['POST'])
@login_required(role='Patient')
def patient_cancel_appointment(app_id):
    patient_id = session['user_id']
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE appointment SET status = 'Cancelled' 
            WHERE app_id = ? AND patient_id = ? AND status = 'Booked'
        ''', (app_id, patient_id))
        
        if cursor.rowcount == 0:
            flash("Appointment not found, already completed, or cancellation window passed.", 'warning')
        else:
            conn.commit()
            flash(f"Appointment {app_id} successfully cancelled.", 'info')

    except Exception as e:
        conn.rollback()
        flash(f'Database error during cancellation: {e}', 'danger')
        
    return redirect(url_for('patient_dashboard'))


# --- Run the App ---
if __name__ == '__main__':
    print(f"Starting Hospital Management System. Database is at: {DATABASE}")
    app.run(debug=True)