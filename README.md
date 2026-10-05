# C2-server
The server maintains a thread-safe SQLite database queue of commands. Target agents periodically initiate outbound HTTP/HTTPS check-ins to retrieve assigned commands, execute them silently as background processes, and report back process exit codes, stdout, and stderr. It was built to eliminate the need for port forwarding or complex VPN setups
