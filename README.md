# Matchmaking Turn Server

<p>A (currently in the works) fast, multi-session TURN server and clients for python, Unreal and Unity. Provides easy pre-grouped or automatic matchmaking and online multiplayer. Also will support arbitrary data transfers over TCP and UDP as well as a bunch of customizability and admin options.</p>

<h2>Overview</h2>
<h3>Setup</h3>
<ol>
  <li>Copy turnserver.py onto a remote hosting server. It doesn't need to be a monster - just the kind usually used for hosting a website will do.</li>
  <li>Either install the Unreal/Unity plugin or see client.py for interfacing with the server from home via python.</li>
  <li>Run turnserver.py.</li>
  <li>Your game/application can now connect with other clients! </li>
</ol>
<p>Detailed installation and usage instructions below.</p>

<h3>Pros:</h3>
<ul>
  <li>Cheap</li>
  <li>Anonymous connections - functions as a VPN</li>
  <li>Multiple sessions, many clients per session.</li>
  <li>Matchmaking included - no need to code it yourself.</li>
  <li>Customizability - file transfers, streaming, games, apps... all at once!</li>
  <li>Ease of use - simple interface and no lengthy server build/deploy loop.</li>
</ul>
<h3>Cons:</h3>
<ul>
  <li>Higher latency than a dedicated game server.</li>
</ul>
