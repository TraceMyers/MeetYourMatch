# Mobile Word Game Turn Server

<p>A simple HTTP TURN server used to demo my game's 2 player multiplayer.  </p>

<p>The server handles matchmaking on a first-come-first-serve basis, or between two specific clients. Once clients are paired, this server relays data between the clients. This will not easily work with game engine net code since it's meant for simple text transfer. A game like mine which transfers very little data and doesn't require frequent communication will be a good fit.</p>
<p>stresstest.py serves as the example code file. Running stresstest.py on a client machine provides summary statistics of performance. A single instance of the server has undergone tests on a 4-core Ubuntu machine and preliminary results show it can (at the very least) handle 30 clients sending single TCP packets 5 times per second. A distributed test will be necessary to better determine maximum load.</p>
<p> I may eventually create a client executable for arbitrary data passing so this repository can be considered something resembling fully-functional software.</p>
<h2>How to use</h2>
<ul>
  <li><p>Clients send http POST requests to the server's public IP + whatever port is specified at startup (or default port is 80). The requests are simple text formatted like so:<blockquote>[incoming symbol],[formatted data],[game/pairing key],[player key],[game received switch]</blockquote></p>
    <ul>
      <li>[incoming symbol]: Tells the server what the client wants, and what kind of formatted data to expect. All of these symbols can be found under the comment reading "incoming symbols"</li>
       <li>[formatted data]: Game data related to the incoming symbol, or nothing. If the incoming symbol is NOTIFY_REGISTER, the data will be a user name. If the incoming symbol is NOTIFY_GAME_UPDATE, the data will be game data. Otherwise, this field is unused.</li>
      <li>[game/pairing key]: If the incoming symbol is NOTIFY_REGISTER(=0), the valid keys are '*' and 'bibbybabbis', which respectively give a normal and a long amount of time to wait between requests before being dropped. '*' is hard-coded, so the latter is for debug purposes. For any other incoming symbol, the key represents the unique pairing registry ID *or* game_registry ID supplied by the server.</li>
      <li>[player key]: During registration, this field indicates who (what name) the client wants to be paired with - and nobody else. '*' for random pairing. After that, the field is unused until the online match has started. Each player either sends a 0 or 1, uniquely. Used for list access in the Game object.</li>
      <li>[player state counter]: Once the match starts, the first value for player state counter should be 0. Each time the player recieves a message back, they increment this counter. If the player's counter stays fixed for every update, the server will continue saving partner data and sending it in larger and larger blocks. Once the counter increases the server will release old data. If the state counter is behind or too ahead, the server will send an error.</li>
    </ul>
    <p>Example 1: <blockquote>0,Davey Jones,*,*,*</blockquote> being sent to the server says "Register me as Davey Jones. I need a key."</p>
    <p>Example 2: <blockquote>2,*,30,*,*</blockquote> says "I want to be paired with another player. The registry key handed to me by the server is 30."</p>
  </li>
  <li>Each request *should* get some kind of data in return. If no packet was recieved, the server expects the client to send the same data again. In the worst case, recieving most error codes indicates that the client must go back to step 1 and register.</li>
  <li>Data coming from the server starting with "0/" indicates success. The client is expected to change their incoming symbol depending on the data they get back from the server, so that the server knows the client agrees with it. For example, The client sends <blockquote>0,Martha Stewart,*,*,*</blockquote> - requesting to register. The server sends back "0/0/15", telling the client registration is successful and their key during the pairing process will be "15". So, the next request to the server should be <blockquote>2,*,15,*,*</blockquote>which asks the server to pair us - client 15 - with another client.</li>
  <li>The pairing process ends when the client gets a C_MSG_START_PLAY message. The message will come with a game key and the client's player key, which need to be supplied with all future requests.</li>
  <li>All formatted data going forward will be game data. The format is determined on the client end, because the server only passes the data along.</li>
  <li>command line arguments are detailed above __main__</p>
</ul>

