-- Secret Console — double-click launcher (macOS).
-- Opens Terminal and runs secret_console_launcher.sh from a known install path.
--
-- Build app:
--   osacompile -o "Secret Console Launcher.app" SecretConsoleLauncher.applescript
--
-- Install: copy secret_console_launcher.sh next to your secret-console checkout
-- (e.g. ~/secret-console/) and ensure it is executable: chmod +x secret_console_launcher.sh

on run
	set homePath to POSIX path of (path to home folder)
	set p1 to homePath & "secret-console/secret_console_launcher.sh"
	set p2 to homePath & "automated-trading-platform/secret-console/secret_console_launcher.sh"
	set launcher to ""
	try
		do shell script "test -f " & quoted form of p1
		set launcher to p1
	on error
		try
			do shell script "test -f " & quoted form of p2
			set launcher to p2
		on error
			display dialog "Could not find secret_console_launcher.sh in:" & return & return & p1 & return & p2 & return & return & "Place secret-console at ~/secret-console or ~/automated-trading-platform/secret-console, or edit this script to add another path." buttons {"OK"} default button "OK" with title "Secret Console Launcher" with icon stop
			return
		end try
	end try
	try
		do shell script "chmod +x " & quoted form of launcher
	end try
	set quotedLauncher to quoted form of launcher
	tell application "Terminal"
		activate
		do script "exec zsh -lc " & quotedLauncher
	end tell
end run
