import os
import re
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from models import db, User, Post, Comment, Like, Notification, follows
from datetime import datetime
from functools import wraps
from sqlalchemy import or_
from dotenv import load_dotenv
import json

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-me')

# ============================================
# DATABASE CONFIG
# ============================================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///social.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ============================================
# FILE UPLOAD CONFIG
# ============================================
POST_IMG_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'posts')
PROFILE_PIC_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'profiles')
app.config['POST_IMG_FOLDER'] = POST_IMG_FOLDER
app.config['PROFILE_PIC_FOLDER'] = PROFILE_PIC_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max

os.makedirs(POST_IMG_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)

ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


db.init_app(app)
bcrypt = Bcrypt(app)

# Load translations from static/locales/*.json
TRANSLATIONS = {}
LOCALES_DIR = os.path.join(app.root_path, 'static', 'locales')
for fname in os.listdir(LOCALES_DIR) if os.path.exists(LOCALES_DIR) else []:
    if fname.endswith('.json'):
        lang = fname.rsplit('.', 1)[0]
        try:
            with open(os.path.join(LOCALES_DIR, fname), 'r', encoding='utf-8') as f:
                TRANSLATIONS[lang] = json.load(f)
        except Exception:
            TRANSLATIONS[lang] = {}


def translate(key):
    """Return translated string for current session language or fallback to key."""
    lang = session.get('lang', 'en')
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS.get('en', {}).get(key, key))


@app.context_processor
def inject_translator():
    return {'t': translate, 'lang': session.get('lang', 'en')}

with app.app_context():
    db.create_all()
    print("✅ Social Media database created successfully!")


# ============================================
# HELPERS
# ============================================
def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXT


def save_image(file, folder, prefix='img'):
    """Save an uploaded image and return (unique_name, original_name)."""
    original_name = file.filename
    safe_name = secure_filename(original_name)
    ext = safe_name.rsplit('.', 1)[1].lower()
    unique_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(folder, unique_name)
    file.save(filepath)
    return unique_name, original_name


def get_liked_post_ids(user_id=None):
    """Return a set of post IDs the given user has liked.
    Returns an empty set when no user is logged in."""
    if not user_id:
        return set()
    return {like.post_id for like in Like.query.filter_by(user_id=user_id).all()}


def add_notification(user_id, notification_type, message, related_user_id=None, post_id=None):
    """Create a notification for a user if the user ID exists."""
    if not user_id:
        return None
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        message=message,
        related_user_id=related_user_id,
        post_id=post_id
    )
    db.session.add(notification)
    db.session.commit()
    return notification


def extract_hashtags(text):
    """Return unique hashtags from a text value in lowercase."""
    if not text:
        return []
    return sorted({tag.lower() for tag in re.findall(r'#([A-Za-z0-9_]+)', text)})


# ============================================
# DECORATORS
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))

        user = User.query.get(session.get('user_id'))
        if user is None:
            session.clear()
            flash('Your session expired. Please log in again.', 'warning')
            return redirect(url_for('login'))

        return f(*args, **kwargs)
    return decorated_function


@app.before_request
def validate_session():
    user_id = session.get('user_id')
    if session.get('logged_in') and user_id is not None:
        user = User.query.get(user_id)
        if user is None:
            session.clear()
            flash('Your session expired. Please log in again.', 'warning')


@app.context_processor
def inject_notification_count():
    if session.get('logged_in'):
        count = Notification.query.filter_by(user_id=session['user_id'], is_read=False).count()
        return {'unread_notification_count': count}
    return {'unread_notification_count': 0}


@app.route('/set_language/<lang>')
def set_language(lang):
    if lang not in TRANSLATIONS:
        lang = 'en'
    session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


# ============================================
# FEED (HOME)
# ============================================
@app.route('/')
def index():
    if not session.get('logged_in'):
        # Show recent public posts to guests
        posts = Post.query.order_by(Post.created_at.desc()).limit(10).all()
        return render_template(
            'index.html',
            posts=posts,
            feed_type='public',
            liked_post_ids=set()
        )

    user = User.query.get(session.get('user_id'))
    if user is None:
        session.clear()
        posts = Post.query.order_by(Post.created_at.desc()).limit(10).all()
        return render_template(
            'index.html',
            posts=posts,
            feed_type='public',
            liked_post_ids=set()
        )

    # Feed: posts from users I follow + my own posts
    followed_ids = [u.id for u in user.following]
    followed_ids.append(user.id)

    posts = Post.query.filter(Post.user_id.in_(followed_ids)).order_by(
        Post.created_at.desc()
    ).all()

    # Pre-compute which posts the current user has liked (avoids N+1 queries in template)
    liked_post_ids = get_liked_post_ids(user.id)

    return render_template(
        'index.html',
        posts=posts,
        feed_type='feed',
        liked_post_ids=liked_post_ids
    )


# ============================================
# EXPLORE
# ============================================
@app.route('/explore')
def explore():
    # All recent posts
    posts = Post.query.order_by(Post.created_at.desc()).limit(50).all()

    # Suggested users (users not followed, excluding self)
    if session.get('logged_in'):
        current_user = User.query.get(session['user_id'])
        following_ids = [u.id for u in current_user.following]
        following_ids.append(current_user.id)
        suggested_users = User.query.filter(
            ~User.id.in_(following_ids)
        ).limit(6).all()
        liked_post_ids = get_liked_post_ids(current_user.id)
    else:
        suggested_users = User.query.limit(6).all()
        liked_post_ids = set()

    return render_template(
        'explore.html',
        posts=posts,
        suggested_users=suggested_users,
        liked_post_ids=liked_post_ids
    )


@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    users = []
    posts = []
    trending_hashtags = []

    if query:
        search_term = query.lstrip('#').strip()
        if search_term:
            users = User.query.filter(
                User.username.ilike(f'%{search_term}%')
            ).order_by(User.username.asc()).limit(8).all()
            posts = Post.query.filter(
                or_(
                    Post.content.ilike(f'%{search_term}%'),
                    Post.content.ilike(f'%#{search_term}%')
                )
            ).order_by(Post.created_at.desc()).limit(20).all()
        else:
            posts = Post.query.filter(Post.content.ilike('%#%')).order_by(Post.created_at.desc()).limit(20).all()
    else:
        recent_posts = Post.query.order_by(Post.created_at.desc()).limit(50).all()
        hashtag_counts = {}
        for post in recent_posts:
            for tag in extract_hashtags(post.content):
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
        trending_hashtags = sorted(hashtag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        posts = recent_posts[:10]

    if session.get('logged_in'):
        liked_post_ids = get_liked_post_ids(session['user_id'])
    else:
        liked_post_ids = set()

    return render_template(
        'search.html',
        query=query,
        users=users,
        posts=posts,
        liked_post_ids=liked_post_ids,
        trending_hashtags=trending_hashtags
    )


# ============================================
# AUTH ROUTES
# ============================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')
        elif User.query.filter_by(username=username).first():
            errors.append('This username is already taken')

        if not email or '@' not in email or '.' not in email:
            errors.append('Please enter a valid email')
        elif User.query.filter_by(email=email).first():
            errors.append('This email is already registered')

        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html', username=username, email=email)

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, password_hash=hashed)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['logged_in'] = True
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ============================================
# PROFILE ROUTES
# ============================================
@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).all()

    is_own = session.get('logged_in') and session['user_id'] == user.id
    is_following = False
    if session.get('logged_in') and not is_own:
        current_user = User.query.get(session['user_id'])
        is_following = current_user.is_following(user)

    liked_post_ids = get_liked_post_ids(session.get('user_id'))

    return render_template('profile.html',
                           user=user,
                           posts=posts,
                           is_own=is_own,
                           is_following=is_following,
                           liked_post_ids=liked_post_ids)


@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        user.bio = request.form.get('bio', '').strip() or None
        user.location = request.form.get('location', '').strip() or None

        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                if not allowed_image(file.filename):
                    flash('Profile picture must be PNG, JPG, GIF, or WEBP.', 'error')
                    return redirect(url_for('edit_profile'))

                if user.profile_picture:
                    try:
                        old = os.path.join(app.config['PROFILE_PIC_FOLDER'], user.profile_picture)
                        if os.path.exists(old):
                            os.remove(old)
                    except Exception as e:
                        print(f'Delete old picture error: {e}')

                unique_name, _ = save_image(file, app.config['PROFILE_PIC_FOLDER'], 'profile')
                user.profile_picture = unique_name

        db.session.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('profile', username=user.username))

    return render_template('edit_profile.html', user=user)


# ============================================
# FOLLOW SYSTEM
# ============================================
@app.route('/follow/<username>', methods=['POST'])
@login_required
def toggle_follow(username):
    target = User.query.filter_by(username=username).first_or_404()
    current = User.query.get(session['user_id'])

    if target.id == current.id:
        flash('You cannot follow yourself.', 'warning')
        return redirect(url_for('profile', username=username))

    if current.is_following(target):
        current.following.remove(target)
        db.session.commit()
        flash(f'Unfollowed {username}.', 'info')
    else:
        current.following.append(target)
        db.session.commit()
        add_notification(
            user_id=target.id,
            notification_type='follow',
            message=f'{current.username} started following you.',
            related_user_id=current.id
        )
        flash(f'Now following {username}!', 'success')

    return redirect(url_for('profile', username=username))


@app.route('/notifications')
@login_required
def notifications():
    user_notifications = Notification.query.filter_by(user_id=session['user_id']).order_by(
        Notification.created_at.desc()
    ).all()
    return render_template('notifications.html', notifications=user_notifications)


@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=session['user_id'], is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'success')
    return redirect(url_for('notifications'))


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=session['user_id']).first_or_404()
    notification.is_read = True
    db.session.commit()
    flash('Notification marked as read.', 'success')
    return redirect(url_for('notifications'))


@app.route('/followers/<username>')
def followers(username):
    user = User.query.filter_by(username=username).first_or_404()
    users = user.followers  # InstrumentedList – iterable directly
    return render_template('followers.html', user=user, users=users, title='Followers')


@app.route('/following/<username>')
def following(username):
    user = User.query.filter_by(username=username).first_or_404()
    users = user.following  # InstrumentedList – iterable directly
    return render_template('following.html', user=user, users=users, title='Following')


# ============================================
# POST ROUTES
# ============================================
@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if request.method == 'POST':
        content = request.form.get('content', '').strip()

        if not content:
            flash('Post content cannot be empty.', 'error')
            return render_template('new_post.html', content=content)

        image_filename = None
        image_original_name = None

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                if not allowed_image(file.filename):
                    flash('Image must be PNG, JPG, GIF, or WEBP.', 'error')
                    return render_template('new_post.html', content=content)

                unique_name, original_name = save_image(file, app.config['POST_IMG_FOLDER'], 'post')
                image_filename = unique_name
                image_original_name = original_name

        new_post = Post(
            content=content,
            image_filename=image_filename,
            image_original_name=image_original_name,
            user_id=session['user_id']
        )
        db.session.add(new_post)
        db.session.commit()

        flash('Post created!', 'success')
        return redirect(url_for('index'))

    return render_template('new_post.html')


@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    liked_post_ids = get_liked_post_ids(session.get('user_id'))
    return render_template('view_post.html', post=post, liked_post_ids=liked_post_ids)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.user_id != session['user_id']:
        flash('You can only delete your own posts.', 'error')
        return redirect(url_for('view_post', post_id=post_id))

    if post.image_filename:
        try:
            filepath = os.path.join(app.config['POST_IMG_FOLDER'], post.image_filename)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f'Delete image error: {e}')

    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'info')
    return redirect(url_for('index'))


@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(post_id=post_id, user_id=session['user_id']).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
    else:
        like = Like(post_id=post_id, user_id=session['user_id'])
        db.session.add(like)
        db.session.commit()

        post_author = Post.query.get(post_id)
        if post_author and post_author.user_id != session['user_id']:
            add_notification(
                user_id=post_author.user_id,
                notification_type='like',
                message=f'{User.query.get(session["user_id"]).username} liked your post.',
                related_user_id=session['user_id'],
                post_id=post_id
            )

    return redirect(request.referrer or url_for('index'))


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get('content', '').strip()

    if not content:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('view_post', post_id=post_id))

    comment = Comment(content=content, user_id=session['user_id'], post_id=post_id)
    db.session.add(comment)
    db.session.commit()

    if post.user_id != session['user_id']:
        add_notification(
            user_id=post.user_id,
            notification_type='comment',
            message=f'{User.query.get(session["user_id"]).username} commented on your post.',
            related_user_id=session['user_id'],
            post_id=post_id
        )

    flash('Comment added!', 'success')
    return redirect(url_for('view_post', post_id=post_id))


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    # Comment author OR post author can delete
    if comment.user_id != session['user_id'] and comment.post.user_id != session['user_id']:
        flash('You cannot delete this comment.', 'error')
        return redirect(url_for('view_post', post_id=comment.post_id))

    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'info')
    return redirect(url_for('view_post', post_id=post_id))


# ============================================
# ERROR HANDLERS
# ============================================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    app.run(debug=True)