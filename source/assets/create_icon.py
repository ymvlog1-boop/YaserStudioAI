from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
p=Path('source/assets');p.mkdir(parents=True,exist_ok=True)
im=Image.new('RGBA',(1024,1024),(7,22,42,255));d=ImageDraw.Draw(im)
d.rounded_rectangle((28,28,996,996),radius=170,outline=(35,235,225,255),width=26)
d.ellipse((140,120,884,864),fill=(7,65,85,255),outline=(0,210,210,255),width=24)
d.polygon([(240,210),(415,210),(512,445),(609,210),(784,210),(590,610),(590,755),(434,755),(434,610)],fill=(231,194,114,255))
font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',78)
d.text((512,875),'Yaser',font=font,anchor='mm',fill=(241,220,162,255))
im.save(p/'yaser.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])