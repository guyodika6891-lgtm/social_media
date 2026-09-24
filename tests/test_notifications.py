import pytest

from app import app, db, User, Notification


@pytest.fixture
def client():
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with app.app_context():
        db.drop_all()
        db.create_all()

        alice = User(username='alice', email='alice@example.com', password_hash='hashed')
        bob = User(username='bob', email='bob@example.com', password_hash='hashed')
        db.session.add_all([alice, bob])
        db.session.commit()

        # capture primitive IDs/usernames while inside the session
        alice_id = alice.id
        bob_id = bob.id
        bob_username = bob.username

    with app.test_client() as client:
        with client.session_transaction() as session:
            session['logged_in'] = True
            session['user_id'] = bob_id
            session['username'] = bob_username
        yield client

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_follow_creates_notification(client):
    response = client.post('/follow/alice', follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        notif = Notification.query.order_by(Notification.id.desc()).first()
        assert notif is not None
        assert notif.type == 'follow'
        assert 'started following' in notif.message.lower()


def test_notifications_page_loads(client):
    response = client.get('/notifications')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Notifications' in html
