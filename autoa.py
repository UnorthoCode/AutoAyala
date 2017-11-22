#!/usr/bin/env python

import sys
import http.client
import urllib.parse
import zlib
import json
import threading
import re
import pprint
import getopt
import argparse		
from bs4 import BeautifulSoup

# helper methods to clean up this junk
def https_connect(host, method, url, params, headers):
	HTTPSConnect = http.client.HTTPSConnection(host)
	HTTPSConnect.request(method, url, params, headers)

	return HTTPSConnect

#NON SSL CONNECTION	
def http_connect(host, method, url, params, headers):
	HTTPSConnect = http.client.HTTPConnection(host)
	HTTPSConnect.request(method, url, params, headers)

	return HTTPSConnect
	
def http_getresponse(msg, con_method, host, method, url, params, headers):
	httpcon = con_method(host, method, url, params, headers)
	httpresp = httpcon.getresponse()
	
	if httpresp.status == 200:
		print (msg, httpresp.status, httpresp.reason)
	else:
		sys.exit(str(httpresp.status) + " " + str(httpresp.reason))

	return httpresp

def http_getheader(msg, header, con_method, host, method, url, params, headers):
	httpresp = http_getresponse(msg, con_method, host, method, url, params, headers)
	return httpresp.getheader(header)
	
def http_getcontent(msg, con_method, host, method, url, params, headers):
	httpresp = http_getresponse(msg, con_method, host, method, url, params, headers)
	return httpresp.read()
	
def http_gzip_decompress_content(msg, con_method, host, method, url, params, headers):
	return zlib.decompress(http_getcontent(msg, con_method, host, method, url, params, headers), 16 + zlib.MAX_WBITS)#.decode('utf-8')

def get_view_cookie():
	ViewHeader = {	
			"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
			"Accept-Encoding":"gzip",
			"Cookie":"ucinetid_auth=no_key", #fix later
			"Connection":"keep-alive",
		 }
	return 	http_getheader("Obtaining view cookie...", "Set-Cookie", http_connect, "spaces.lib.uci.edu", "GET","/booking/ayala", None, ViewHeader)
	
def get_available_dates(view_cookie):
	DateParams = urllib.parse.urlencode({
						"gid":"13646", #Ayala id
						"cw":"7" #calendar week?
				 })

	DateHeader = {	
						"Accept":"application/json, text/javascript, */*; q=0.01",
						"Accept-Encoding":"gzip",
						"Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
						"X-Requested-With":"XMLHttpRequest",
						"Referer":"http://spaces.lib.uci.edu/booking/ayala",
						"Content-Length":len(DateParams),
						"Cookie":view_cookie,
						"Connection":"keep-alive",
				 }

	return http_gzip_decompress_content("Obtaining available dates...", http_connect, "spaces.lib.uci.edu", "POST", "/process_roombookings.php?m=cal_dates", DateParams, DateHeader)
	
class cRooms:
	drooms = {}
	def __del__(self):
		self.drooms.clear()
		
	def __init__(self):
		self.drooms.clear()
		
	def add(self, room, id, start, end):
		inserted = False #ugly and gross way
		ltime_headers = []
		ltimes = [] # list of times
		times = { # dictionary to make it data easier to parse	
			"id":id,
			"start":start,
			"end":end
		}
		
		#***WE WILL ABUSE THE ORDERING PROPERTY OF THE PARSED TABLE***
		
		if room in self.drooms:
			for time_header in self.drooms[room]:
				if time_header['end'] == start: # last entry is the start of open slot, therefore add to the end of the list

					time_header['time_slots'].append(times) # obtain the time slot list

					## update the header
					time_header['end'] = end
					time_header['minutes'] += 30
					inserted = True
					break # dont spend more time scanning
					
			if inserted == False: # we do not have any matching cases and need to create a new one 
				#print(times)
				#print(time_header)
				
				ltimes.append(times)
				
				time_header = {
					"start": start, 
					"end": end, 
					"minutes": 30, 
					"time_slots": ltimes
				}
				self.drooms[room].append(time_header)

		else: # new entry 
			ltimes.append(times)
			
			time_header = {
				"start": start,
				"end": end,
				"minutes": 30,
				"time_slots": ltimes
			}
			
			ltime_headers.append(time_header)
			
			self.drooms[room] = ltime_headers # add new entry to the table.

def parse_Table(content):
	rooms = cRooms()
	regextime = re.compile("[[0-9]+:[0-9]+..")
	regexslots = re.compile("'(.*?)'")

	find_html = BeautifulSoup(content, "html5lib")
	for x in find_html.find_all("a"):
		rslots = regexslots.findall(x['onclick'])	
		rtime = regextime.findall(rslots[1])
		#print(x)
		rooms.add(rslots[0], x['id'], rtime[0], rtime[1])
		
		#print(m[0], x['id'], m[1])

	#pprint.pprint(rooms.drooms)
	
	return rooms.drooms.copy()

def get_table_data(date):
	TableParams = urllib.parse.urlencode(
			  { 
					"m":"calscroll",
					"gid":"13646",
					"date":date,
					"nocache":"1507681629098" # what is this?
			  })

	TableHeader = {	
					"Accept-Encoding":"gzip",
					"X-Requested-With":"XMLHttpRequest",
					"Referer":"http://spaces.lib.uci.edu/booking/Ayala", #required because the website uses referer as a location
					"Cookie":"ucinetid_auth=no_key", #fix later
					"Connection":"keep-alive",
					"Content-Length":len(TableParams)
				}

	return http_gzip_decompress_content("Obtaining table {0}...".format(date), http_connect, "spaces.lib.uci.edu", "POST", "/process_roombookings.php?" + TableParams, TableParams, TableHeader)

def parse_engine(dparsed, date):
	httptable = get_table_data(date)
	availrooms = parse_Table(httptable)	
	print ("Parsing table {0}".format(date))
	dparsed[date] = availrooms

def generate_results(curr_results, date, room, time_header):
	if date not in curr_results: # create empty date slot
		curr_results[date] = {}
	
	if room not in curr_results[date]: # there is a room already in the list
		curr_results[date][room] = []
		
	matched_slots = curr_results[date][room] # get old list
	matched_slots.append(time_header)

def autoayala(date, room, minutes, start, end):
	dparsed = {}
	results = {}
	
	view_cookie = get_view_cookie()
	#print ("View Cookie: {0}".format(view_cookie))
	
	if date == '*':
		threads = []
		
		open_dates = get_available_dates(view_cookie)
		#print ("Dates: {0}".format(open_dates))

		JsonTableData = json.loads(open_dates)
		
		for d in JsonTableData['availDates']: # DD:MM:YYYY
			t = threading.Thread(target=parse_engine, args=(dparsed, d,))
			threads.append(t)
    
		for t in threads:
			t.start()
			
		for t in threads:
			t.join()
	else: # only get one date table
		t = threading.Thread(target=parse_engine, args=(dparsed, date,))
		t.start()
		t.join()
    
	#print('dparsed')
	#pprint.pprint(dparsed)
	print("Building filtered table...")
	if room != '*' and date != '*': # find slot for specific room and date
	
		if room in dparsed[date]:
			for s in dparsed[date][room]:
				if s['minutes'] >= minutes:
					if start == '*' or s['start'] == start:
						generate_results(results, date, room, s)
						
	elif room != '*': # find slot for specific room
		for d in dparsed:
			if room in dparsed[d]:
				for s in dparsed[d][room]:
					if s['minutes'] >= minutes:
						if start == '*' or s['start'] == start:
							generate_results(results, d, room, s)
							
	elif room == '*' and date == '*': # find anything
		for d in dparsed:
			for r in dparsed[d]:
				for s in dparsed[d][r]:
					if s['minutes'] >= minutes:
						if start == '*' or s['start'] == start:
							generate_results(results, d, r, s)
							
	elif room == '*':
		for r in dparsed[date]:
			for s in dparsed[date][r]:
				if s['minutes'] >= minutes:
					if start == '*' or s['start'] == start:
						generate_results(results, date, r, s)
					
	return results
	
def main(argv):
	parser = argparse.ArgumentParser()
	
	parser.add_argument('-d', dest='date', default='*', help='format DD-MM-YYYY')
	parser.add_argument('-r', dest='room', default='*', help='Ayala Science XXX')
	parser.add_argument('-m', dest='minutes', default='30', help='minutes')
	parser.add_argument('-s', dest='start', default='*', help='format HH:MM(am|pm)')
	parser.add_argument('-e', dest='end', default='*', help='format HH:MM(am|pm)')
	parser.add_argument('-f', dest='filedir', default='null', help='list of accounts')
	
	args = parser.parse_args()
	
	results = autoayala(args.date, args.room, int(args.minutes), args.start, args.end)
	pprint.pprint(results)

if __name__ == "__main__":
   main(sys.argv[1:])
