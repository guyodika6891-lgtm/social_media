from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


# ============================================
# FOLLOWS ASSOCIATION TABLE (Self-referential M:N)
# ============================================
follows = db.Table(
    'follows',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)


# ============================================
# USER MODEL
# ============================================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(150), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Simple relationships
    posts = db.relationship('Post', backref='author', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='author', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='user', lazy=True, cascade='all, delete-orphan')
    notifications = db.relationship(
        'Notification',
        backref='owner',
        lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='Notification.user_id'
    )

    # Self-referential many-to-many (FOLLOW SYSTEM)
    # NOTE: lazy=True -> returns a list-like InstrumentedList (use |length / len() / `in`)
    followers = db.relationship(
        'User',
        secondary=follows,
        primaryjoin=(follows.c.followed_id == id),
        secondaryjoin=(follows.c.follower_id == id),
        backref='following',
        lazy=True
    )

    def is_following(self, user):
        """Check if this user follows another user."""
        return user in self.following

    def __repr__(self):
        return f'<User {self.username}>'


# ============================================
# POST MODEL
# ============================================
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    image_original_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='post', lazy=True, cascade='all, delete-orphan')

    def is_liked_by(self, user):
        """Check if a specific user liked this post."""
        return Like.query.filter_by(post_id=self.id, user_id=user.id).first() is not None

    def __repr__(self):
        return f'<Post by {self.author.username}>'


# ============================================
# COMMENT MODEL
# ============================================
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

    def __repr__(self):
        return f'<Comment by {self.author.username}>'


# ============================================
# LIKE MODEL
# ============================================
class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_like'),
    )

    def __repr__(self):
        return f'<Like by {self.user.username}>'


# ============================================
# NOTIFICATION MODEL
# ============================================
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    related_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', foreign_keys=[user_id])
    related_user = db.relationship('User', foreign_keys=[related_user_id])

    def __repr__(self):
        return f'<Notification {self.type} for user {self.user_id}>'