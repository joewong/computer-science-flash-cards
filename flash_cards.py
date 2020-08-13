import os
import sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, \
    render_template, flash

app = Flask(__name__)
app.config.from_object(__name__)

# Load default config and override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'db', 'cards.db'),
    SECRET_KEY='development key',
    USERNAME='admin',
    PASSWORD='default'
))
app.config.from_envvar('CARDS_SETTINGS', silent=True)


def connect_db():
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = sqlite3.Row
    return rv


def init_db():
    db = get_db()
    with app.open_resource('data/schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


# -----------------------------------------------------------

# Uncomment and use this to initialize database, then comment it
#   You can rerun it to pave the database and start over
# @app.route('/initdb')
# def initdb():
#     init_db()
#     return 'Initialized the database.'


@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('general'))
    else:
        return redirect(url_for('login'))


@app.route('/cards')
def cards():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    query = '''
        SELECT id, type, front, back, known
        FROM cards
        ORDER BY id DESC
    '''
    cur = db.execute(query)
    cards = cur.fetchall()
    type_query = '''
        SELECT id, card_name
        FROM card_types
        ORDER BY id ASC
    '''
    type_cur = db.execute(type_query)
    card_types = type_cur.fetchall()
    return render_template('cards.html', cards=cards, card_types=card_types, filter_name="all")


@app.route('/card_types')
def card_types():
    type_query = '''
    SELECT 
        card_types.id,
        card_types.card_name,
        SUM(cards.known) AS known,
        COUNT(cards.id) - SUM(cards.known) as unknown
    FROM
        card_types
    INNER JOIN
	    cards on cards.type = card_types.id
    GROUP BY
        card_types.id,
        card_types.card_name
    ORDER BY card_types.id ASC
    '''
    db = get_db()
    type_cur = db.execute(type_query)
    card_types = type_cur.fetchall()
    return render_template('card_types.html', card_types=card_types)


@app.route('/filter_cards/<filter_name>')
def filter_cards(filter_name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    # TODO make this an inner join to get the multiple choice summary
    fullquery = """
        SELECT cards.id, cards.type, cards.front, cards.back, cards.known
        FROM cards
        INNER JOIN card_types ON cards.type = card_types.id 
        WHERE card_types.card_name = ?
        ORDER BY cards.id DESC
    """
    cur = db.execute(fullquery, [filter_name])
    cards = cur.fetchall()
    return render_template('cards.html', cards=cards, filter_name=filter_name)


@app.route('/add', methods=['POST'])
def add_card():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    db.execute('INSERT INTO cards (type, front, back) VALUES (?, ?, ?)',
               [request.form['type'],
                request.form['front'],
                request.form['back']
                ])
    db.commit()
    flash('New card was successfully added.')
    return redirect(url_for('cards'))

@app.route('/test/<card_name>')
def run_test(card_name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # Create a new test 
    db = get_db()
    create_test_query = """
    INSERT INTO test_multiple_choice (card_type_id) 
    SELECT id 
    FROM card_types 
    WHERE card_name = ?
    """
    test_result = db.execute(create_test_query, [card_name])
    db.commit() 
    test_id = test_result.lastrowid

    # Insert 10 questions
    create_test_questions_query = """
    INSERT INTO 
        test_multiple_choice_cards (test_multiple_choice_id, card_id) 
    SELECT 
        test_multiple_choice.id, cards.id
    FROM 
        cards, card_types, test_multiple_choice
    WHERE 
        card_types.id = cards.type 
    AND test_multiple_choice.card_type_id = cards.type
    AND test_multiple_choice.id = ?
    AND card_types.card_name = ?
    ORDER BY RANDOM()
    LIMIT 10
    """
    db.execute(create_test_questions_query, [test_id, card_name])
    db.commit()

    # Insert the randomised multiple choice ordering
    create_test_questions_order_query = """
    INSERT INTO test_multiple_choice_questions_order 
        (position,
         test_multiple_choice_card_id,
         card_multiple_choice_id)
    SELECT 
        ROW_NUMBER() OVER (
			PARTITION BY card_multiple_choices.card_id
			ORDER BY RANDOM()
		) as position,
        test_multiple_choice_cards.id,
		card_multiple_choices.id
    FROM
        test_multiple_choice_cards, card_multiple_choices
    WHERE
	card_multiple_choices.card_id = test_multiple_choice_cards.card_id
    AND test_multiple_choice_id = ?
	ORDER BY test_multiple_choice_cards.card_id
    """
    db.execute(create_test_questions_order_query, [test_id])
    db.commit()

    return render_template('multiple_choice_card_test.html')

@app.route('/clear_knowns/card/<card_type>')
def clear_knowns(card_type):
    if not session.get('logged_in'):
        return redirect(url_for('login')) 
    db = get_db()
    query = """
    UPDATE cards SET known = 0 
    WHERE type = ? 
    """
    db.execute(query, card_type)
    db.commit()
    return redirect('/card_types')


@app.route('/test/<card_name>')
def card_test(card_name):
    if not session.get('logged_in'):
        return redirect(url_for('login')) 
    # TODO select 10 random cards

    return render_template('test.html')


@app.route('/update/multiple_choices/card/<card_id>')
def update_multiple_choice(card_id):
    db = get_db()
    card_query = '''
        SELECT id, type, front, back, known
        FROM cards
        WHERE id = ?
    '''
    card_cur = db.execute(card_query, [card_id])
    card = card_cur.fetchone()
    query = '''
        SELECT card_types.id, card_types.card_name FROM card_types
        INNER JOIN cards ON card_types.id = cards.type
        WHERE cards.id = ?
        '''
    type_cur = db.execute(query, [card_id])
    card_type = type_cur.fetchone() 
    multiple_choices_query = '''
        SELECT 
            card_multiple_choices.id,
            card_multiple_choices.card_id,
            card_multiple_choices.card_choice,
            card_multiple_choices.correct_choice
        FROM card_multiple_choices
        INNER JOIN cards ON cards.id = card_multiple_choices.card_id
        WHERE cards.id = ?
    '''
    multiple_cur = db.execute(multiple_choices_query, [card_id])
    multiple_choices = multiple_cur.fetchall()
    return render_template('update_multiple_choices.html', card=card, card_type=card_type, multiple_choices=multiple_choices)

@app.route('/create/multiple_choice/card/<card_id>', methods=['GET','POST'])
def create_multiple_choice(card_id):
    db = get_db()
    new_choice_query = '''
    INSERT INTO card_multiple_choices (card_id, card_choice) VALUES (?,?)
    '''
    db.execute(new_choice_query, [int(card_id), request.form['choice']])
    db.commit()
    return redirect('/update/multiple_choices/card/'+str(card_id))

@app.route('/update/correct_multiple_choice/card/<card_id>/<choice_id>')
def update_correct_multiple_choice(card_id, choice_id):
    # TODO toggle value in database
    db = get_db()
    query = """UPDATE card_multiple_choices 
    SET correct_choice = NOT correct_choice
    WHERE id = ?
    """ 
    db.execute(query, [choice_id])
    db.commit()
    return redirect('/update/multiple_choices/card/'+str(card_id))


@app.route('/edit/<card_id>')
def edit(card_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    query = '''
        SELECT id, type, front, back, known
        FROM cards
        WHERE id = ?
    '''
    cur = db.execute(query, [card_id])
    card = cur.fetchone()
    return render_template('edit.html', card=card)


@app.route('/edit_card', methods=['POST'])
def edit_card():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    selected = request.form.getlist('known')
    known = bool(selected)
    db = get_db()
    command = '''
        UPDATE cards
        SET
          type = ?,
          front = ?,
          back = ?,
          known = ?
        WHERE id = ?
    '''
    db.execute(command,
               [request.form['type'],
                request.form['front'],
                request.form['back'],
                known,
                request.form['card_id']
                ])
    db.commit()
    flash('Card saved.')
    return redirect(url_for('cards'))


@app.route('/delete/<card_id>')
def delete(card_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    db.execute('DELETE FROM cards WHERE id = ?', [card_id])
    db.commit()
    flash('Card deleted.')
    return redirect(url_for('cards'))


@app.route('/card/<card_type>')
@app.route('/card/<card_type>/<card_id>')
def card(card_type=None, card_id=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return memorize(card_type, card_id)


@app.route('/general')
@app.route('/general/<card_id>')
def general(card_id=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return memorize("general", card_id)


@app.route('/code')
@app.route('/code/<card_id>')
def code(card_id=None):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return memorize("code", card_id)


def memorize(card_type, card_id):
    #return redirect(url_for('cards'))
    if card_id:
        card = get_card_by_id(card_id)
    else:
        card = get_card(card_type)
    if not card:
        flash("You've learned all the " + card_type + " cards.")
        return redirect(url_for('cards'))
    short_answer = "short answer..." #(len(card['back']) < 75)
    return render_template('memorize.html',
                           card=card,
                           card_type=card_type,
                           short_answer=short_answer)


def get_card(card_type):
    db = get_db()

    query = '''
    SELECT
        cards.id, type, front, back, known
    FROM cards, card_types
    WHERE
    cards.type = card_types.id
    AND card_types.card_name = ?
    AND known = 0
    ORDER BY RANDOM()
    LIMIT 1
    '''

    cur = db.execute(query, [card_type])
    return cur.fetchone()


def get_card_by_id(card_id):
    db = get_db()

    query = '''
      SELECT
        id, type, front, back, known
      FROM cards
      WHERE
        id = ?
      LIMIT 1
    '''

    cur = db.execute(query, [card_id])
    return cur.fetchone()


@app.route('/mark_known/<card_id>/<card_type>')
def mark_known(card_id, card_type):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db = get_db()
    query = """
    UPDATE cards 
    SET known = 1 
    WHERE id = ?
    """
    db.execute(query, [card_id])
    db.commit()
    flash('Card marked as known.')
    return redirect("/card/" + card_type)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] != app.config['USERNAME']:
            error = 'Invalid username or password!'
        elif request.form['password'] != app.config['PASSWORD']:
            error = 'Invalid username or password!'
        else:
            session['logged_in'] = True
            session.permanent = True  # stay logged in
            return redirect(url_for('cards'))
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash("You've logged out")
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0')
