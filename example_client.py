import socket
from struct import pack

a = 1
b = 2
c = 33000
d = 3.14159
e = bytes('0123456789', 'utf-8')
f = b''
for i in range(45):
    f += b'0123456789'
f += b'0123'
# data = pack('<2BHf2sB', a, b, c, d, e, f)
data = pack('<2BHf10s454s', a, b, c, d, e, f)
print(data)

quit()
with open('url.txt') as f:
    url = f.readline()
url = '192.168.0.203'
port = 8192
buffer_size = 1024
server_loc = (url, port)

udp_client_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
udp_client_socket.sendto(k, server_loc)
server_msg = udp_client_socket.recvfrom(buffer_size)
print(server_msg)