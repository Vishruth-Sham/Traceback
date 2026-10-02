on focusTracebackTab(refreshExisting)
    try
        if not (application "Google Chrome" is running) then return false
        tell application "Google Chrome"
            repeat with chromeWindow in windows
                set tabURLs to URL of tabs of chromeWindow
                repeat with tabNumber from (count of tabURLs) to 1 by -1
                    set tabURL to item tabNumber of tabURLs
                    if tabURL is "http://localhost:3000" or tabURL starts with "http://localhost:3000/" then
                        set chromeTab to tab tabNumber of chromeWindow
                        set active tab index of chromeWindow to tabNumber
                        set index of chromeWindow to 1
                        if refreshExisting then reload chromeTab
                        activate
                        return true
                    end if
                end repeat
            end repeat
        end tell
    on error
        if not refreshExisting then
            tell application "Google Chrome" to activate
            return true
        end if
        return false
    end try
    return false
end focusTracebackTab

on startTraceback(refreshExisting)
    set appFolder to POSIX path of (path to me)
    set repoPath to do shell script ("cd " & quoted form of (appFolder & "..") & " && pwd")
    set pythonPath to repoPath & "/.venv/bin/python"
    set servicePath to repoPath & "/scripts/traceback_service.py"
    try
        with timeout of 180 seconds
            do shell script (quoted form of pythonPath & " " & quoted form of servicePath & " start")
        end timeout
        if not my focusTracebackTab(refreshExisting) then open location "http://localhost:3000"
    on error errorMessage
        display dialog "Traceback could not start:" & return & return & errorMessage buttons {"OK"} default button "OK" with icon stop
    end try
end startTraceback

on run
    my startTraceback(true)
end run

on reopen
    my startTraceback(false)
end reopen

on idle
    return 60
end idle

on quit
    set appFolder to POSIX path of (path to me)
    set repoPath to do shell script ("cd " & quoted form of (appFolder & "..") & " && pwd")
    set pythonPath to repoPath & "/.venv/bin/python"
    set servicePath to repoPath & "/scripts/traceback_service.py"
    try
        with timeout of 90 seconds
            do shell script (quoted form of pythonPath & " " & quoted form of servicePath & " stop")
        end timeout
        continue quit
    on error errorMessage
        display dialog "Traceback could not stop cleanly:" & return & return & errorMessage buttons {"OK"} default button "OK" with icon stop
    end try
end quit
