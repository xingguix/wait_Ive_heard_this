import requests

title = 'Zoo (From "Zootopia 2"/Soundtrack Version)'
artist = "Disney/Shakira"

print(requests.get("https://tools.rangotec.com/api/anon/lrc", params={'title': title, 'artist': artist}).json())
