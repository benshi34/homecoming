# Google Photos and Drive

Photo times, places and people from Google Photos, and the text of your Drive files (imported as documents). Can be very large.

Where: https://takeout.google.com/

1. Create a separate export with only Google Photos and Drive ticked.
   This can run to hundreds of GB. Check free space first.

2. Choose 50 GB parts, then Create export.

3. Download only as many parts as fit on this Mac or an external drive.

4. Takeout leaves out comment threads and version history. Those come from the Drive API: a folder per file with drive.json (files.get, comments.list, revisions.list), the file as it is now, and revisions/<id>.txt, under imports/drive.
   Any tool that writes that layout works; rclone already signed in to Drive is enough to make one.

The download link usually comes in 1 day, at most 3 days. It works for 7 days. The file: `takeout-<date>-<n>-001.zip, 50 GB parts`.
