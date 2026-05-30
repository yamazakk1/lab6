from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, asc
from models import db, Course, Category, User, Review
from tools import CoursesFilter, ImageSaver

bp = Blueprint('courses', __name__, url_prefix='/courses')

COURSE_PARAMS = [
    'author_id', 'name', 'category_id', 'short_desc', 'full_desc' 
]

def params():
    return { p: request.form.get(p) or None for p in COURSE_PARAMS }

def search_params():
    return {
        'name': request.args.get('name'),
        'category_ids': [x for x in request.args.getlist('category_ids') if x],
    }

@bp.route('/')
def index():
    courses = CoursesFilter(**search_params()).perform()
    pagination = db.paginate(courses)
    courses = pagination.items
    categories = db.session.execute(db.select(Category)).scalars()
    return render_template('courses/index.html',
                           courses=courses,
                           categories=categories,
                           pagination=pagination,
                           search_params=search_params())

@bp.route('/new')
@login_required
def new():
    course = Course()
    categories = db.session.execute(db.select(Category)).scalars()
    users = db.session.execute(db.select(User)).scalars()
    return render_template('courses/new.html',
                           categories=categories,
                           users=users,
                           course=course)

@bp.route('/create', methods=['POST'])
@login_required
def create():
    f = request.files.get('background_img')
    img = None
    course = Course()
    try:
        if f and f.filename:
            img = ImageSaver(f).save()

        image_id = img.id if img else None
        course = Course(**params(), background_image_id=image_id)
        db.session.add(course)
        db.session.commit()
    except Exception as err:
        flash(f'Возникла ошибка при записи данных в БД. Проверьте корректность введённых данных. ({err})', 'danger')
        db.session.rollback()
        categories = db.session.execute(db.select(Category)).scalars()
        users = db.session.execute(db.select(User)).scalars()
        return render_template('courses/new.html',
                            categories=categories,
                            users=users,
                            course=course), 400

    flash(f'Курс {course.name} был успешно добавлен!', 'success')
    return redirect(url_for('courses.index'))

@bp.route('/<int:course_id>')
def show(course_id):
    course = db.get_or_404(Course, course_id)
    recent_reviews = db.session.execute(
        db.select(Review)
        .filter_by(course_id=course_id)
        .order_by(desc(Review.created_at))
        .limit(5)
    ).scalars().all()
    
    user_review = None
    if current_user.is_authenticated:
        user_review = db.session.execute(
            db.select(Review).filter_by(course_id=course_id, user_id=current_user.id)
        ).scalar()
    
    return render_template('courses/show.html', 
                         course=course, 
                         recent_reviews=recent_reviews,
                         user_review=user_review)


@bp.route('/<int:course_id>/reviews')
def reviews_list(course_id):
    course = db.get_or_404(Course, course_id)
    page = request.args.get('page', 1, type=int)
    per_page = 10
    sort_by = request.args.get('sort_by', 'newest')
    
    query = db.select(Review).filter_by(course_id=course_id)
    
    if sort_by == 'newest':
        query = query.order_by(desc(Review.created_at))
    elif sort_by == 'positive':
        query = query.order_by(desc(Review.rating), desc(Review.created_at))
    elif sort_by == 'negative':
        query = query.order_by(asc(Review.rating), desc(Review.created_at))
    
    pagination = db.paginate(query, page=page, per_page=per_page)
    reviews = pagination.items
    
    user_review = None
    if current_user.is_authenticated:
        user_review = db.session.execute(
            db.select(Review).filter_by(course_id=course_id, user_id=current_user.id)
        ).scalar()
    
    return render_template('courses/reviews_list.html',
                         course=course,
                         reviews=reviews,
                         pagination=pagination,
                         sort_by=sort_by,
                         user_review=user_review)


@bp.route('/<int:course_id>/review/create', methods=['POST'])
@login_required
def create_review(course_id):
    course = db.get_or_404(Course, course_id)
    
    existing_review = db.session.execute(
        db.select(Review).filter_by(course_id=course_id, user_id=current_user.id)
    ).scalar()
    
    if existing_review:
        flash('Вы уже оставили отзыв на этот курс.', 'warning')
        return redirect(url_for('courses.show', course_id=course_id))
    
    rating = request.form.get('rating', type=int)
    text = request.form.get('text')

    if rating is None or rating < 0 or rating > 5:
        flash('Оценка должна быть от 0 до 5.', 'danger')
        return redirect(url_for('courses.show', course_id=course_id))
    
    if not text or len(text.strip()) < 5:
        flash('Текст отзыва слишком короткий (минимум 5 символов).', 'danger')
        return redirect(url_for('courses.show', course_id=course_id))
    
    try:
        review = Review(
            rating=rating,
            text=text.strip(),
            course_id=course_id,
            user_id=current_user.id
        )
        db.session.add(review)
        
        course.rating_sum += rating
        course.rating_num += 1
        
        db.session.commit()
        flash('Ваш отзыв успешно добавлен!', 'success')
        
        next_page = request.form.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('courses.show', course_id=course_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении отзыва: {str(e)}', 'danger')
        return redirect(url_for('courses.show', course_id=course_id))