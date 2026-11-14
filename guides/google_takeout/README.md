# Google

Gmail, search and YouTube history, Chrome, Calendar, Contacts, Keep, Tasks, Google Chat, Maps and your saved lists.

Where: https://takeout.google.com/

An agent doing this for you says which site it will open (takeout.google.com) before opening it, and opens no other. Homecoming reads only the file you bring back.

1. Sign in with your own Google account. Check the name in the top right.

2. Click "Deselect all", then tick Calendar, Chrome, Contacts, Gemini, Google Chat, Keep, Mail, Maps, Maps (your places), My Activity, Saved, Tasks, and YouTube and YouTube Music.
   The counter at the top should go up with each tick. Saved holds your Maps lists (Want to go, Favorites, your own). Leave Google Photos and Drive for their own export.

3. My Activity → Multiple formats → Activity records: choose JSON.

4. YouTube and YouTube Music → Multiple formats → history: choose JSON. Under "All YouTube data included", untick videos.

5. Next step: send download link via email, export once, .zip, 50 GB parts (one download, not several). Create export.

The download link usually comes in 8 hours, at most 2 days. It works for 7 days. The file: `takeout-<date>-<n>-001.zip, often several parts`.

Not in it:
- Work and school Google accounts need their own export.
