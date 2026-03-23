
CREATE TABLE IF NOT EXISTS the_mind_games (
  game_id VARCHAR PRIMARY KEY,
  status VARCHAR,
  current_level INTEGER DEFAULT 1,
  lives INTEGER,
  shurikens INTEGER,
  cards_played INTEGER[]
);

CREATE TABLE IF NOT EXISTS the_mind_players (
  game_id VARCHAR,
  chat_id VARCHAR,
  username VARCHAR,
  user_id VARCHAR,
  cards INTEGER[],
  is_ready BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (game_id, chat_id)
);