import pytest

from app import app, db, User, Post


@pytest.fixture
def client():
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(username='alex', email='alex@example.com', password_hash='hashed')
        db.session.add(user)
        db.session.commit()

        post = Post(content='Love #launch day and welcome to the team!', user_id=user.id)
        db.session.add(post)
        db.session.commit()

    with app.test_client() as client:
        yield client

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_search_route_returns_post_and_user_matches(client):
    response = client.get('/search?q=launch')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'launch' in html.lower()
    assert 'alex' in html.lower()


def test_search_route_handles_empty_query(client):
    response = client.get('/search')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Trending' in html or 'Search' in html


def test_stale_session_redirects_to_public_feed(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 999
        session['username'] = 'ghost-user'

    response = client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Recent Posts' in html or 'Login' in html
