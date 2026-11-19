# The TV box launcher

`launcher.html` is a page saved **on the TV box** (the HP behind the TV). The box opens it first, and it
opens the tap board.

**Why:** the board is a web page. If Edge starts while the box has no connection (the 3:30am restart racing
the Wi-Fi, a power blip, a real outage), Edge shows its own "Looks like you're not connected to the internet"
page and stays on it until someone restarts the box. That happened on Sunday Nov 15 2026. A page saved on the
box always loads, so it can wait for the connection and then open the board by itself.

**What it does**
- Checks that the board can actually be fetched, twice in a row, then opens it. On a normal start that takes
  about two seconds and you only see dark green.
- If the board is not up within 6 seconds it shows a holding card: the logo, "The tap list will be right back",
  "Ask your bartender what's pouring", and a small line at the bottom saying why (no internet at the box, or
  the site is not answering) and when it last checked.
- Keeps checking every few seconds, forever. When the connection returns, the board appears on its own.

Once the board is open, the board looks after itself: it only reloads after it has fetched the new page
(see `src/js/3-qol.js`).

## Setting it up on the box (about 10 minutes, once)

You need the keyboard and mouse on the box and the `admin` password.

1. **Switch to admin.** Ctrl+Alt+Delete → Sign out → sign in as `admin`.

2. **Save the launcher and try it.** Right-click Start → Terminal (Admin), paste this, press Enter:

   ```powershell
   New-Item -ItemType Directory -Force -Path "C:\Users\Public\Board" | Out-Null
   Invoke-WebRequest "https://plattpark.github.io/liveboard/kiosk/launcher.html" -OutFile "C:\Users\Public\Board\launcher.html" -UseBasicParsing
   Start-Process msedge "file:///C:/Users/Public/Board/launcher.html"
   ```

   Edge opens and the board should appear within a few seconds.

   Test it: close Edge, turn Wi-Fi off from the taskbar, then paste just the last line (`Start-Process ...`)
   again. After about 6 seconds you should see the green "The tap list will be right back" card. Turn Wi-Fi
   back on. The board should appear by itself within about 15 seconds. Close Edge.

3. **Point the kiosk at it.** Settings → Accounts → Other users → Kiosk → the `board` kiosk → Microsoft Edge,
   and change the address to:

   ```
   file:///C:/Users/Public/Board/launcher.html
   ```

   If there is nowhere to edit the address: choose Remove kiosk, then Set up a kiosk again with the same
   answers as before (account `board`, app Microsoft Edge, "As a digital sign or interactive display") and
   the address above.

4. **Restart the box.** It should sign itself in, show dark green for a second or two, then the board.

**If step 4 shows anything else** (a blank page, an error, a message that the file can't be opened): repeat
step 3 with the old address, `https://plattpark.github.io/liveboard/platt-park-live-board-v4.html`. Nothing
else on the box was changed, so that puts it back exactly as it was. Whether Windows kiosk mode will open a
file from disk has not been tried on this box yet; step 2 proves the launcher itself works there.

## Changing it

Edit `kiosk/build.py` and run `python3 kiosk/build.py`. The fonts and logo are embedded so the card needs no
network. The box keeps its own saved copy: to update it, run the download line from step 2 again as admin.

## While you're back there

The box is on Wi-Fi. If there is a network jack within reach, a cable takes the Wi-Fi out of the picture.
