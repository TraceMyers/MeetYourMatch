# MYM: Meet Your Match

<p>A (currently in the works) simple, fast, multi-session STUN and TURN server with direct support for python, Unreal and GameMaker clients. Provides pre-grouped or automatic matchmaking and session handling. Because clients connect directly to each other, computational and network load are removed from the server, allowing for many more clients per dollar spent on remote hosting.</p>

<h2>Overview</h2>
<h3>Setup</h3>
<ol>
  <li>Rent a server.</li>
  <li>Copy turnserver.py onto the server.</li>
  <li>Either install the game engine plugin or see client.py for use with python.</li>
  <li>Read the forthcoming documentation and connect your game's code to the plugin.</li>
  <li>Run matchmaker.py on the server.</li>
  <li>Your game/application can now connect with other clients!</li>
</ol>
<p>Detailed installation and usage instructions coming once the project is ready.</p>

<h3>Pros:</h3>
<ul>
  <li>Inexpensive compared to dedicated server hosting.</li>
  <li>Many sessions, many clients per session are both possible.</li>
  <li>Matchmaking included - no need to code it yourself.</li>
  <li>Customizability - use as a proxy, or use it for games or apps!</li>
  <li>Ease of use - simple interface and no lengthy server build/deploy loop.</li>
</ul>
<h3>Cons:</h3>
<ul>
  <li>Often higher latency than a dedicated game server - depends on host connection.</li>
  <li>Until a feature called 'host rotation' is implemented, hosts may leave and sessions will abruptly end.</li>
</ul>
