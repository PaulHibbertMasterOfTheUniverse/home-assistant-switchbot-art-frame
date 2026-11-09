"""Prepare the verified 13.3-inch Frame 2 six-colour display buffer."""
import io
import colorsys
from PIL import Image, ImageOps

PALETTE=((0,0,0),(255,255,255),(255,255,0),(159,0,0),(0,0,255),(0,143,0))
def vendor_adjust(image):
    """Recovered app defaults: HSV saturation 1.05, black offset .08, contrast 5."""
    data=bytearray()
    for r,g,b in image.getdata():
        h,s,v=colorsys.rgb_to_hsv(r/255,g/255,b/255)
        rgb=colorsys.hsv_to_rgb(h,min(1,s*1.05),v)
        data.extend(int(min(255,max(0,c*255-20.4)*1.1025)) for c in rgb)
    return Image.frombytes('RGB',image.size,bytes(data))
def stucki(image, indexed=False):
    """Recovered native six-ink Stucki kernel; vendor divisor is 64, not 42."""
    w,h=image.size;src=image.tobytes();out=bytearray(w*h)
    rows=[[0]*(3*w) for _ in range(3)]
    offsets=((1,0,8),(2,0,4),(-2,1,2),(-1,1,4),(0,1,8),(1,1,4),(2,1,2),(-2,2,1),(-1,2,2),(0,2,4),(1,2,2),(2,2,1))
    for y in range(h):
        for x in range(w):
            i=x*3;p=(y*w+x)*3
            r=max(0,min(255,src[p]+rows[0][i]));g=max(0,min(255,src[p+1]+rows[0][i+1]));b=max(0,min(255,src[p+2]+rows[0][i+2]))
            best=0;distance=10**9
            for k,(pr,pg,pb) in enumerate(PALETTE):
                d=(r-pr)**2+(g-pg)**2+(b-pb)**2
                if d<distance:best=k;distance=d
            out[y*w+x]=best;pr,pg,pb=PALETTE[best];er=r-pr;eg=g-pg;eb=b-pb
            for dx,dy,weight in offsets:
                xx=x+dx
                if 0<=xx<w and y+dy<h:
                    j=xx*3;row=rows[dy];row[j]+=(er*weight)>>6;row[j+1]+=(eg*weight)>>6;row[j+2]+=(eb*weight)>>6
        rows=rows[1:]+[[0]*(3*w)]
    result=Image.frombytes('P',image.size,bytes(out));result.putpalette([v for c in PALETTE for v in c]+[0]*750)
    return result if indexed else result.convert('RGB')

def panel_bytes(content):
    with Image.open(io.BytesIO(content)) as source:
        image=ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'),(1600,1200))
        image=image.rotate(270,expand=True)
    palette=Image.new('P',(1,1))
    colours=[(0,0,0),(255,255,255),(255,255,0),(255,0,0),(0,0,255),(0,255,0)]
    palette.putpalette([v for colour in colours for v in colour]+[0]*750)
    pixels=image.quantize(palette=palette,dither=Image.Dither.FLOYDSTEINBERG).tobytes()
    mapping=[0,1,2,3,5,6]+[0]*250
    packed=bytes((mapping[pixels[i]]<<4)|mapping[pixels[i+1]] for i in range(0,len(pixels),2))
    # Each half of the panel is stored as its own sequence of scanlines.
    return b''.join(packed[row*600+offset:row*600+offset+300]
                    for offset in (0,300) for row in range(1600))

def original_large_scanlines(packed):
    """31.5-inch app changeBinData31: pair rows, then eight controller strips."""
    if len(packed)!=1843200:raise ValueError('Invalid 31.5-inch display buffer')
    result=bytearray()
    for start,end in ((0,200),(200,400),(400,600),(600,640),(640,840),(840,1040),(1040,1240),(1240,1280)):
        for row in range(0,1440,2):
            for column in range(start,end):
                a=packed[column+1280*row];b=packed[column+1280*(row+1)]
                result.extend(((a&240)|((b&240)>>4),((a&15)<<4)|(b&15)))
    return bytes(result)

def cloud_assets(content,model,size=None):
    """App-compatible cloud assets using an explicit panel profile.

    Original 13.3 and 31.5 scanline layouts come from the app's
    changeBinData13 and changeBinData31 routines respectively.
    """
    size=size or ('7.3' if model=='frame1' else '13.3')
    dimensions={'7.3':(800,480),'13.3':(1600,1200),'31.5':(2560,1440)}
    if size not in dimensions or (model=='frame2' and size!='13.3'):raise ValueError('Unsupported frame panel profile')
    with Image.open(io.BytesIO(content)) as source:
        image=ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'),dimensions[size])
        out=io.BytesIO();image.save(out,'JPEG',quality=92);main=out.getvalue()
        thumb=image.copy();thumb.thumbnail((240,240));out=io.BytesIO();thumb.save(out,'JPEG',quality=80)
        thumbnail=out.getvalue()
    if size=='13.3':native=panel_bytes(main)
    else:
        if size=='7.3':image=image.rotate(270,expand=True)
        palette=Image.new('P',(1,1));colours=[(0,0,0),(255,255,255),(255,255,0),(255,0,0),(0,0,255),(0,255,0)]
        palette.putpalette([v for colour in colours for v in colour]+[0]*750)
        pixels=(stucki(vendor_adjust(image), indexed=True).tobytes() if size=='31.5' else image.quantize(palette=palette,dither=Image.Dither.FLOYDSTEINBERG).tobytes());mapping=[0,1,2,3,5,6]+[0]*250
        native=bytes((mapping[pixels[i]]<<4)|mapping[pixels[i+1]] for i in range(0,len(pixels),2))
        if size=='31.5':native=original_large_scanlines(native)
    return (main,thumbnail,native)
