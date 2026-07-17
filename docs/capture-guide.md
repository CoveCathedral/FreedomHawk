# Capturing one real frame to validate the protocol

This is the one step that needs a phone. Its whole purpose is to grab **one real message**
that the old Firehawk Remote app sends to the pedal for a *known* action (say, nudging the
Amp Drive knob), so we can compare it byte-for-byte against what FreedomHawk *would* send
for the same action (Device → View Outgoing Messages). If they match, the reverse
engineering is confirmed and the last two inferred constants (the float type tag and the
transport port) are locked in.

You've never done this — that's fine. It's mostly toggles and one file copy. Take it slow;
nothing here changes anything on your pedal.

## What you need

- An Android phone that can run the old **Firehawk Remote** app and pair with the pedal.
  (If the app won't get past its dead login, this route is blocked and we lean on static
  analysis instead — tell me and we'll regroup.)
- A computer with the phone plugged in by USB.
- Android platform-tools (`adb`) on the computer — I can walk you through installing it.

## Step 1 — Turn on Developer Options (one time)

1. On the phone: **Settings → About phone**.
2. Tap **Build number** seven times. It'll say "You are now a developer."
3. Go back to **Settings → System → Developer options**.

## Step 2 — Turn on the Bluetooth capture log

1. In **Developer options**, find **Enable Bluetooth HCI snoop log**.
2. Set it to **Enabled** (or "Filtered"/"All" if it asks — "All" is safest).
3. Toggle Bluetooth **off and back on** so the log starts fresh.

From now on the phone records all Bluetooth traffic to a file until you turn this back off.

## Step 3 — Do ONE known thing

1. Open the old Firehawk Remote app and connect to the pedal.
2. Change **exactly one** parameter, and remember it precisely. A good choice: go to the
   Amp and nudge **Drive** by one notch. Just one change — that keeps the capture clean.
3. That's it. Close the app.

## Step 4 — Get the log off the phone

With the phone plugged in and USB debugging allowed:

```
adb bugreport firehawk_capture
```

This makes a `firehawk_capture.zip`. Inside it, the file we want is somewhere like
`FS/data/misc/bluetooth/logs/btsnoop_hci.log` (the exact path varies by phone). Unzip and
find `btsnoop_hci.log`. On some phones you can instead pull it directly:

```
adb pull /data/misc/bluetooth/logs/btsnoop_hci.log
```

Send me that `btsnoop_hci.log` (or the whole zip) and stop here — I'll do the rest.

## Step 5 — Turn the capture log back off

Back in **Developer options**, set **Enable Bluetooth HCI snoop log** to **Disabled**. No
reason to keep logging all your Bluetooth traffic.

## What I do with it

I open the log, filter to the RFCOMM data going to the pedal, and find the frame that
starts with the sync bytes `55 55`. Because you told me exactly which knob you moved, I can
line the captured bytes up against FreedomHawk's staged message for that same edit
(`Device → View Outgoing Messages`) and against `tools/crc_hunt.py`. Three things fall out:

- confirmation the frame + CRC are exactly right,
- the real value of the float **type tag**, and
- the **transport port** in the 8-byte header.

That closes the last gap, and live control moves from "reverse-engineered" to "validated."

## If the app won't run

If the Firehawk Remote login wall blocks the app, we can't capture its traffic this way.
That's the one scenario the handoff flagged. If it happens, don't worry — we keep chipping
at those last two constants statically, and the entire rest of the stack is already
confirmed and tested. Tell me and we'll pick the next thread.
