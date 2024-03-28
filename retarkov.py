import logging
import markovify
import discord
import re
import random
import aiosqlite
import asyncio

# token
TOKEN = 'TOKEN'

# loggin
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# sqlite
async def get_db_connection():
    return await aiosqlite.connect('chat_data.db')

async def generate_dynamic_response(tags, preferred_tags=None):
    models_to_combine = [text_models[tag] for tag in tags if tag in text_models]
    
    if preferred_tags:
        weights = [3 if tag in preferred_tags else 1 for tag in tags if tag in text_models]  # higher weight for preferred tags
    else:
        weights = [2 if tag in tags else 1 for tag in tags if tag in text_models]  # default weights

    combined_model = markovify.combine(models_to_combine, weights)
    return combined_model.make_sentence(tries=100)

responses_enabled = True

# creating tables for msgs
async def create_tables():
    async with get_db_connection() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                author TEXT,
                content TEXT,
                tag TEXT
            )
        ''')
        await conn.commit()

# markov chain models for each tag
text_models = {}

# regex for tags
question_regex = re.compile(r'\?$')
humor_regex = re.compile(r'^\b(lol|lmao)\b$', re.IGNORECASE)
opinion_regex = re.compile(r'\b(agree|disagree|true|false|right|wrong|correct|incorrect)\b', re.IGNORECASE)
openq_regex = re.compile(r'^\b(why|how|what)\b.{0,20}$', re.IGNORECASE)

# antonyms for opinions
opinion_antonyms = {
    'agree': 'disagree',
    'disagree': 'agree',
    'true': 'false',
    'false': 'true',
    'right': 'wrong',
    'wrong': 'right',
    'correct': 'incorrect',
    'incorrect': 'correct'
}

# reaction threshold "notable" tag
NOTABLE_THRESHOLD = 2

# channel ID for collecting and sending messages
CHANNEL_ID = 1234

# save data to the database
async def save_data(message_data):
    try:
        async with get_db_connection() as conn:
            await conn.execute('''
                INSERT INTO messages (author, content, tag)
                VALUES (?, ?, ?)
            ''', (message_data['author'], message_data['content'], message_data['tag']))
            await conn.commit()
    except Exception as e:
        logging.error(f"Failed to save data for author {message_data['author']}: {e}")


# train a markov chain model for each tag
async def train_models():
    global text_models
    text_models = {}

    async with get_db_connection() as conn:
        cursor = await conn.execute('SELECT DISTINCT tag FROM messages')
        tags = [row[0] for row in await cursor.fetchall()]

        for tag in tags:
            cursor = await conn.execute('SELECT content FROM messages WHERE tag = ?', (tag,))
            text = '\n'.join([row[0] for row in await cursor.fetchall()])
            text_models[tag] = markovify.NewlineText(text)

# default tag weights
TAG_WEIGHTS = {
    'general': 1,
    'question': 1,
    'opinion': 1.5,
    'openq': 1,
    'humor': 2,
    'answer': 1.5,
    'notable': 2
}

# baseline probability for responding
BASE_RESPONSE_PROBABILITY = 0.02  # 1 in 50

async def calculate_response_probability(tags):
    probability = BASE_RESPONSE_PROBABILITY
    for tag in tags:
        if tag in TAG_WEIGHTS:
            probability += TAG_WEIGHTS[tag]
    return min(probability, 1.0)  # ensure probability doesn't exceed 1.0

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
client = discord.Client(intents=intents)

# on_ready handler
@client.event
async def on_ready():
    logging.info(f'Logged in as {client.user}')
    await create_tables()
    await train_models()

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    print(f"Message from {message.author}: {message.content}")
    global CHANNEL_ID
    if message.author == client.user:
        return

    if CHANNEL_ID is not None and message.channel.id != CHANNEL_ID:
        return

    # calculate response probability
    tags = ['general']  # default tag for all messages
    if question_regex.search(message.content):
        tags.append('question')
    if opinion_regex.search(message.content):
        tags.append('opinion')
    if openq_regex.search(message.content):
        tags.append('openq')

    probability = await calculate_response_probability(tags)

    # decide whether to respond
    if random.random() < probability:
        # store the message and its tags
        for tag in tags:
            message_data = {
                'author': str(message.author),
                'content': message.content,
                'tag': tag
            }
            await save_data(message_data)

        # check if the message is a reply to another message
        if message.reference is not None:
            replied_message = await message.channel.fetch_message(message.reference.message_id)

            # check if the reply contains "lol" or "lmao"
            if humor_regex.search(message.content):
                message_data = {
                    'author': str(replied_message.author),
                    'content': replied_message.content,
                    'tag': 'humor' # tag the original msg as humor
                }
                await save_data(message_data)

            # check if the replied message is a question or open-ended question
            async with get_db_connection() as conn:
                cursor = await conn.execute('SELECT * FROM messages WHERE content = ? AND (tag = ? OR tag = ?)', (replied_message.content, 'question', 'openq'))
                if await cursor.fetchone() is not None:
                    message_data = {
                        'author': str(message.author),
                        'content': message.content,
                        'tag': 'answer'
                    }
                    await save_data(message_data)

        # setchannel command
        if message.content.startswith('!setchannel'):
            if message.author.guild_permissions.administrator:
                CHANNEL_ID = message.channel.id
                await message.channel.send(f'Channel set to {message.channel.mention}')
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # retrain with new stored msgs
        if message.content.startswith('!reload'):
            if message.author.guild_permissions.administrator:
                await train_models()
                await message.channel.send('Models reloaded successfully.')
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # import up to 100 old msgs
        if message.content.startswith('!import'):
            if message.author.guild_permissions.administrator:
                try:
                    limit = int(message.content.split()[1])
                    if limit > 100:  # rate limits mayne
                        limit = 100
                        await message.channel.send('Importing limited to 100 messages due to Discord rate limits.')
                    channel = client.get_channel(CHANNEL_ID)
                    await store_old_messages(channel, limit=limit)
                    await train_models()
                    await message.channel.send(f'Models trained on the last {limit} messages.')
                except (ValueError, IndexError):
                    await message.channel.send('Usage: !import <number_of_messages>')
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # modify a tag weight
        if message.content.startswith('!settagweight'):
            if message.author.guild_permissions.administrator:
                try:
                    tag, weight = message.content.split()[1:3]
                    weight = float(weight)
                    if tag not in TAG_WEIGHTS:
                        await message.channel.send(f'Invalid tag: {tag}')
                        return
                    TAG_WEIGHTS[tag] = weight
                    await message.channel.send(f'Tag weight for "{tag}" set to {weight}')
                except (ValueError, IndexError):
                    await message.channel.send('Usage: !settagweight <tag> <weight>')
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # modify the baseline probability
        if message.content.startswith('!setbaseprobability'):
            if message.author.guild_permissions.administrator:
                try:
                    probability = float(message.content.split()[1])
                    if probability < 0 or probability > 1:
                        await message.channel.send('Probability must be between 0 and 1.')
                        return
                    global BASE_RESPONSE_PROBABILITY
                    BASE_RESPONSE_PROBABILITY = probability
                    await message.channel.send(f'Base response probability set to {probability}')
                except (ValueError, IndexError):
                    await message.channel.send('Usage: !setbaseprobability <probability>')
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # stats stuff
        if message.content.startswith('!brainpower'):
            if message.author.guild_permissions.administrator:
                config_message = "Current Configuration:\n\n"
                config_message += f"Base Response Probability: {BASE_RESPONSE_PROBABILITY}\n\n"
                config_message += "Tag Weights:\n"
                for tag, weight in TAG_WEIGHTS.items():
                    config_message += f"{tag}: {weight}\n"

                async with get_db_connection() as conn:
                    cursor = await conn.execute('SELECT COUNT(*) FROM messages')
                    total_messages = (await cursor.fetchone())[0]
                    config_message += f"\nTotal Messages Collected: {total_messages}\n\n"

                    config_message += "Messages Collected by Tag:\n"
                    cursor = await conn.execute('SELECT tag, COUNT(*) FROM messages GROUP BY tag')
                    tag_counts = await cursor.fetchall()
                    for tag, count in tag_counts:
                        config_message += f"{tag}: {count}\n"

                await message.channel.send(config_message)
            else:
                await message.channel.send('You must have admin permissions to use this command.')
            return

        # check if the message is a question or an open-ended question
        if question_regex.search(message.content) or openq_regex.search(message.content):
            preferred_tags = ['answer']  # heavily weight "answer" tag for response
        else:
            preferred_tags = None

        # check if the message contains three or more keywords from a notable message
        async with get_db_connection() as conn:
            cursor = await conn.execute('SELECT * FROM messages WHERE tag = ?', ('notable',))
            notable_data = await cursor.fetchall()

        for notable_message in notable_data:
            notable_words = notable_message[2].lower().split()
            message_words = message.content.lower().split()
            common_words = set(notable_words) & set(message_words)

            if len(common_words) >= 3:
                # generate a random opinion
                opinion = await generate_dynamic_response(['opinion', 'general'])

                response = f"{notable_message[0]} said '{notable_message[2]}' about that.... {opinion}" #quote notable message from author, followed by opinion
                await message.channel.send(response)
                return  

        # generate a response
        response = await generate_dynamic_response(tags, preferred_tags)

        # check if the message contains an opinion word
        opinion_match = opinion_regex.search(message.content)
        if opinion_match:
            opinion_word = opinion_match.group().lower()
            if opinion_word in opinion_antonyms:
                antonym = opinion_antonyms[opinion_word]
                response = f"Actually, that's {antonym}, and {await generate_dynamic_response(['humor', 'general'])}" #they are always wrong

        # check if the message is a reply to a question or open-ended question with a previously tagged answer
        if message.reference is not None:
            replied_message = await message.channel.fetch_message(message.reference.message_id)

            async with get_db_connection() as conn:
                cursor = await conn.execute('SELECT * FROM messages WHERE content = ? AND (tag = ? OR tag = ?)', (replied_message.content, 'question', 'openq'))
                if await cursor.fetchone() is not None:
                    cursor = await conn.execute('SELECT * FROM messages WHERE content = ? AND tag = ?', (message.content, 'answer'))
                    if await cursor.fetchone() is not None:
                        # check if the answer contains two or more keywords more stuff to do here
                        answer_words = message.content.lower().split()
                        keyword_count = sum(1 for word in answer_words if word in ['agree', 'disagree', 'true', 'false', 'right', 'wrong', 'correct', 'incorrect'])

                        if keyword_count >= 2:
                            opinion_match = opinion_regex.search(message.content)
                            if opinion_match:
                                opinion_word = opinion_match.group().lower()
                                if opinion_word in opinion_antonyms:
                                    antonym = opinion_antonyms[opinion_word]
                                    response = f"Actually, that's {antonym}, and {await generate_dynamic_response(['humor', 'general'])}" 

        # check if the message contains specific phrases, more logic to do here
        if any(phrase in message.content.lower() for phrase in ["did you know", "have you heard", "have you seen", "did you see", "what does this mean?", "whats that", "whats that mean", "what happened"]):
            response = await generate_dynamic_response(['general'])

        if response:
            await message.channel.send(response)

# on_reaction_add event handler
@client.event
async def on_reaction_add(reaction, user):
    global CHANNEL_ID
    if user == client.user:
        return

    # check if the message is in the channel
    if CHANNEL_ID is not None and reaction.message.channel.id != CHANNEL_ID:
        return

    # check if the message has enough reactions to be tagged as "notable" (currently 2)
    if reaction.count >= NOTABLE_THRESHOLD:
        message = reaction.message
        message_data = {
            'author': str(message.author),
            'content': message.content,
            'tag': 'notable'
        }
        await save_data(message_data)

# fetch and store old messages from a channel, this probably shouldnt exist
async def store_old_messages(channel: discord.TextChannel, limit: int = None):
    """
    Fetch and store old messages from a Discord channel.

    Args:
        channel (TextChannel): The channel to fetch messages from.
        limit (int, optional): The maximum number of messages to fetch. Defaults to None (no limit).
    """
    async with get_db_connection() as conn:
        async for message in channel.history(limit=limit):
            if message.author != client.user:
                tags = ['general']
                if question_regex.search(message.content):
                    tags.append('question')
                if opinion_regex.search(message.content):
                    tags.append('opinion')
                if openq_regex.search(message.content):
                    tags.append('openq')

                for tag in tags:
                    message_data = {
                        'author': str(message.author),
                        'content': message.content,
                        'tag': tag
                    }
                    await save_data(message_data)

client.run(TOKEN)
