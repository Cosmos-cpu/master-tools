import requests
import json
import urllib.parse
import tkinter as tk
import vlc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

HYDRUS_API_URL = "http://127.0.0.1:45869"
HYDRUS_API_KEY = "99adfca3533b407b76a8bdc7ba0043b94e17a383b7d5bac06811cd9e6a0bc705"
PROXY_SERVER_URL = "http://127.0.0.1:8080/video"
tags = ["anal"]


class Proxy(BaseHTTPRequestHandler):

    def do_GET(self):
        hash = self.path.split("/")[-1]

        r = requests.get(
            "http://127.0.0.1:45869/get_files/file",
            headers={
                "Hydrus-Client-API-Access-Key": HYDRUS_API_KEY
            },
            params={
                "hash": hash
            },
            stream=True
        )

        self.send_response(200)
        self.send_header(
            "Content-Type",
            r.headers["Content-Type"]
        )
        self.end_headers()

        for chunk in r.iter_content(65536):
            self.wfile.write(chunk)

proxy_server = ThreadingHTTPServer(("127.0.0.1", 8080), Proxy)
threading.Thread(
    target=proxy_server.serve_forever,
    daemon=True
).start()


encoded_tags = urllib.parse.quote(json.dumps(tags), safe="")

req = requests.get(
    f"{HYDRUS_API_URL}/get_files/search_files"
    f"?tags={encoded_tags}",
    headers={'Hydrus-Client-API-Access-Key': HYDRUS_API_KEY},
)

get_file = f"{PROXY_SERVER_URL}/video/21d2f0f64ec6f853f0753703c2cd1adac7a0ba056fcbd4ef42a49e1bc482121c"

def play_video(path):
    root = tk.Tk()
    root.geometry("800x600")
    
    player = vlc.Instance().media_player_new()
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True)
    
    player.set_hwnd(frame.winfo_id())
    
    media = vlc.Instance().media_new(path)
    player.set_media(media)
    
    def play():
        player.play()
    
    tk.Button(root, text="Play", command=play).pack()
    
    root.mainloop()

play_video(get_file)

# print(req.request.url)
# print(req.request.headers)
# print(req.request.body)
# print(req.request.method)
# print(req)