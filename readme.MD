
## WORK IN PROGRESS

trying to make a personality disordered markov chain chatbot that doesnt need AI to be contextual

### message tagging & storage

all messages are stored in aiosqlite db. messages are automatically tagged based on hardcoded keywords. tagging logic is implemented in `on_message`, using regex
tags influence response generation. current tags:

- **general**: default all messages
- **question**: stored message ends with ?
- **opinion**: contains words like agree, disagree, false, true, correct, incorrect, right, wrong, etc.
- **openq**: open-ended questions with "why," "how," "what." and less than 3 words
- **humor**: messages that people have replied "lol" or "lmao" to
- **answer**: replies to msgs tagged questions or open-ended questions.
- **notable**: receives atleast 2 reactions.

all messages also store author for some cheeky quoting shenanigans. plan to implement infinite more logic ig.
https://patents.google.com/patent/US20230394595A1/ - maybe some ideas from discords bigbrother patent in regards to autotagging at some point

### response generation

responses are generated from markov chain models:

1. **tag identification**: tags from the incoming message are identified.
2. **response probability calculation**: uses `calculate_response_probability` to determine if the bot should respond. base probability is 1 in 50, but tags have weights that can influence response chance
3. **tag based response generation**: for example, if we detect an opinion it might disagree with that opinion and insert an opinion of its own. or it might answer questions with answers. under special conditions it might directly quote an author by name and concatenate with its own retarded opinion
3. **markov chain model combination**: we train each tag with its own model but combine every model for every generation
4. **response generation**: generated responses are weighted by trigger tag association to try to be contextual to the trigger

markov chains model text generation from a corpus. `markovify` is used for model creation and manipulation.

- models are created for each tag with `train_models`, pulling messages from a database.
- response generation combines these models based on tag relevance and preferred tags to output a weighted response.

## commands

- `!setchannel`: set the channel we store msgs from / respond in (maybe set this manually)
- `!reload`: retrain all models with new stored messages since last reload (currently this retrains from SCRATCH each time.) be aware
- `!import [limit]`: train models on recent messages (up to 100 due to rate limits, this probs shouldnt exist)
- `!settagweight [tag] [weight]`: adjust tag weights for response calculation
- `!setbaseprobability [probability]`: adjust the base response probability
- `!brainpower`: display current configuration, weights and database statistics

need admin 4 all commands

## todo

some sort of system that lets ppl add, modify tags without hardcoding everything
absolutely NO AI. you see, if he is coherent without language processing ability, his wisdom is divine
oh yeah, and probably should test stuff at some point

