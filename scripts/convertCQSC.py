#!/usr/bin/env python
#
# Convert Columbia Quote Speech Corpus xml to our format

import argparse
import json
import os
import re
import sys
import logging
import traceback
import util

import xml.dom.minidom as minidom

from sets import Set
from collections import Counter

from util import get_all_text
from util import readCharacters

FORMAT = '%(asctime)-15s [%(levelname)s] %(message)s'
logging.basicConfig(format=FORMAT)
log = logging.getLogger('index')
log.setLevel(logging.INFO)

def isSectionHeading(text):
    return text.startswith('VOLUME') or text.startswith('STAVE') or text.startswith('CHAPTER') or text.startswith('PART')

def strToCharacter(str):
    fields = str.split(';')
    aliases = [fields[0]] + fields[2:]
    character = { 'name': fields[0].replace(' ', '_'), 'gender': mapGender(fields[1]), 'aliases': aliases}
    return character

def mapGender(gender):
    if gender == 'M':
        return 'male'
    elif gender == 'F':
        return 'female'
    else:
        return gender

def lowercaseTags( node ):
    if node.nodeType ==  node.ELEMENT_NODE:
        node.tagName = node.tagName.lower()
        node.nodeName = node.tagName
    for child_node in node.childNodes:
        lowercaseTags(child_node)

def stripSectionTags( dom ):
    paragraphTypes = ['heading', 'paragraph']
    for ptype in paragraphTypes:
        for paragraph in dom.getElementsByTagName(ptype):
            for child in paragraph.childNodes:
                paragraph.parentNode.insertBefore(child.cloneNode(True), paragraph)
            paragraph.parentNode.insertBefore(dom.createTextNode('\n'), paragraph)
            paragraph.parentNode.removeChild(paragraph)

def toChapters( dom ):
    chapters = []
    paras = []
    elementCnt = 0
    for doc in dom.getElementsByTagName('doc'):
      for text in dom.getElementsByTagName('text'):
        for child in text.childNodes:
            if child.nodeType == child.ELEMENT_NODE and child.tagName == 'heading':
                text = get_all_text(child)
                isSectionStart = isSectionHeading(text) or ' ' not in text
                if isSectionStart and elementCnt > 0:
                    chapters.append(paras)
                    paras = []
                    elementCnt = 0
            if child.nodeType == child.ELEMENT_NODE:
                if child.tagName == 'paragraph':
                    elementCnt += 1
                if len(paras) == 0:
                    paras.append(dom.createTextNode('\n'))
            paras.append(child)
    if elementCnt > 0:
        chapters.append(paras)
    return chapters

def writeXml( dom, filename, includeSectionTags ):
    if not includeSectionTags:
        stripSectionTags(dom)
    with open(filename, 'w') as output:
        output.write(dom.toxml("utf-8"))
#       output.write(dom.toprettyxml(encoding="utf-8"))

def writeEntities(dom, filename):
    with open(filename, 'w') as output:
       output.write(dom.toprettyxml(encoding="utf-8"))

def writeConverted( dom, filename, splitChapters, includeSectionTags):
    if splitChapters:
        # Create minidom for each chapter
        chapters = toChapters(dom)
        (temp, ext) = os.path.splitext(filename)
        (base, ext2) = os.path.splitext(temp)
        ext = ext2 + ext
        impl = minidom.getDOMImplementation()
        for chindex, chapter in enumerate(chapters):
            chdom = impl.createDocument(None, "doc", None)
            textElem = chdom.createElement('text')
            for para in chapter:
                textElem.appendChild(para.cloneNode(True))
            docElem = chdom.documentElement
            charactersElems = dom.getElementsByTagName('characters')
            for elem in charactersElems:
                docElem.appendChild(elem.cloneNode(True))
            docElem.appendChild(textElem)
            chfile = base + '-' + str(chindex) + ext
            writeXml(chdom, chfile, includeSectionTags)
    else:
        writeXml(dom, filename, includeSectionTags)

def findCharacter(entity, characters):
    # Tries to match entity to list of characters
    cnt = Counter()
    for index,character in enumerate(characters):
        for alias1 in entity['aliases']:
            for alias2 in character['aliases']:
                if alias2.lower() == alias1.lower():
                    cnt[index] += 1
    best = cnt.most_common(1)
    if len(best) > 0:
        character = characters[best[0][0]]
        return character
    else:
        return None

def stripCharactersFromAttributes(element, s):
    if element.attributes:
        for attrName, attrValue in element.attributes.items():
            element.setAttribute(attrName, re.sub(s, '', attrValue))
    for child in element.childNodes:
        stripCharactersFromAttributes(child, s)

def addNestedQuotes(element):
    # Strip ' from attributes
    stripCharactersFromAttributes(element, "'")
    str = element.toxml("utf-8")
    str2 = re.sub(r"(\W)'((?![ts]\W|re\W|ll\W).*?)'(\W)",r"\1<QUOTE>'\2'</QUOTE>\3", str)
    if not str == str2:
        # Nested quote hack for doyle_boscombe
        if 'Witness:' in str2:
            pieces = re.split("(Witness.*?:\s*|The Coroner:\s*|A Juryman:\s*)", str2)
            for i,p in enumerate(pieces):
                if i % 2 == 0 and i > 0:
                    speaker = ""
                    if 'Witness' in pieces[i-1]:
                        speaker = 'James_McCarthy'
                    elif 'Coroner' in pieces[i-1]:
                        speaker = 'Coroner'
                    elif 'Juryman' in pieces[i-1]:
                        speaker = 'Juryman'
                    if '<QUOTE>' in pieces[i]:
                        pieces[i] = re.sub(r"(.*?)(\s*<QUOTE>)",r'<QUOTE speaker="">\1</QUOTE>\2', p)
                    else:
                        pieces[i] = '<QUOTE speaker="">' + p + '</QUOTE>'
                    pieces[i] = pieces[i].replace('speaker=""', 'speaker="' + speaker + '"', 1)
                #elif i % 2 == 1:
                #    pieces[i] = re.sub(r"(Witness|The Coroner|A Juryman)",r'<MENTION entityType="PERSON">\1</MENTION>',p)
            str2 = "".join(pieces)
            #str2 = re.sub(r"(Witness:\s*|The Coroner:\s*|A Juryman:\s*)(.*?[.?])",r"\1<QUOTE>\2</QUOTE>", str2)
        #print str2
        try:
            return minidom.parseString(str2).documentElement
        except:
            log.error('Invalided nested quote xml: ' + str2)
    return None

def convert(input, outfilename, charactersFile, mentionLevel, splitChapters, includeSectionTags, extractNestedQuotes):
    #print input
    #print output
    nertypes = ['PERSON', 'ORGANIZATION', 'LOCATION']
    dom = minidom.parse(input)
    root = dom.documentElement
    if charactersFile:
        characters = readCharacters(charactersFile)
        characterDict = { x['name']:x for x in characters }
    else:
        characters = None
        characterDict = None
    # Process paragraphs
    entities = {}
    mentionIdToEntityId = {}
    # clean paragraphs
    for paragraph in root.getElementsByTagName('PARAGRAPH'):
        if len(paragraph.childNodes) == 1:
            child = paragraph.childNodes[0]
            if child.nodeType ==  child.ELEMENT_NODE:
                if child.tagName == 'HEADING':
                    # single child that is heading (remove paragraph wrapping)
                    paragraph.removeChild(child)
                    paragraph.parentNode.replaceChild(child, paragraph)
                    continue
        if len(paragraph.childNodes) < 5:
            text = get_all_text(paragraph)
            if isSectionHeading(text):
                paragraph.tagName = 'HEADING'
                paragraph.nodeName = 'HEADING'
    # Clean extracted mentions in HEADING
    for paragraph in root.getElementsByTagName('HEADING'):
        for nertype in nertypes:
            for mention in paragraph.getElementsByTagName(nertype):
                t = dom.createTextNode(get_all_text(mention))
                mention.parentNode.replaceChild(t, mention)
    # Convert mentions under PARAGRAPH
    for paragraph in root.getElementsByTagName('PARAGRAPH'):
        for nertype in nertypes:
            for mention in paragraph.getElementsByTagName(nertype):
                mention.tagName = 'MENTION'
                mention.nodeName = 'MENTION'
                mention.setAttribute('entityType', nertype)
                entityId = mention.getAttribute('entity')
                mentionId = mention.getAttribute('id')
                if not entityId in entities:
                    # it would be great if the entities had names
                    entities[entityId] = {
                        'id': entityId,
                        'entityType': nertype,
                        'gender': mapGender(mention.getAttribute('gender')),
                        'aliases': Set()
                    }
                name = get_all_text(mention)
                entities[entityId]['aliases'].add(name)
                mentionIdToEntityId[mentionId] = entityId
    # Add characters
    entityElementsByType = {
        'PERSON': { 'elements': dom.createElement('PERSONS'), 'name': 'PERSON'},
        'LOCATION': { 'elements': dom.createElement('LOCATIONS'), 'name': 'LOCATION'},
        'ORGANIZATION': { 'elements': dom.createElement('ORGANIZATIONS'), 'name': 'ORGANIZATION'},
    }
    for entityId, entity in entities.iteritems():
        # try to match entity with our list of characters
        if characters:
            character = findCharacter(entity, characters)
            if character:
                entity['name'] = character['name']
        info = entityElementsByType[entity['entityType']]
        element = dom.createElement(info['name'])
        for k, v in entity.iteritems():
            if k == 'aliases':
                element.setAttribute(k,';'.join(v))
            else:
                element.setAttribute(k,v)
        info['elements'].appendChild(element)
    # Wrap headings and paragraphs in text tag
    newdoc = dom.createElement('DOC')
    root.tagName = 'TEXT'
    root.nodeName = 'TEXT'
    entitiesElement = dom.createElement('ENTITIES')
    entitiesElement.appendChild(entityElementsByType['PERSON']['elements'])
    entitiesElement.appendChild(entityElementsByType['LOCATION']['elements'])
    entitiesElement.appendChild(entityElementsByType['ORGANIZATION']['elements'])
    #newdoc.appendChild(entitiesElement)
    newdoc.appendChild(root)
    dom.appendChild(newdoc)

    # Add characters
    if characters:
        charactersElement = dom.createElement('CHARACTERS')
        for character in characters:
            element = dom.createElement('CHARACTER')
            charactersElement.appendChild(element)
            for k, v in character.iteritems():
                if k == 'aliases':
                    element.setAttribute(k,';'.join(v))
                else:
                    element.setAttribute(k,v)
        newdoc.insertBefore(charactersElement, root)

    # Go over mentions and fix there speakerId
    mentionIdToSpanId = {}
    nextMentionSpanId = 0
    mentions = dom.getElementsByTagName('MENTION')
    mentionIdToMention = {}
    for mention in mentions:
        entityId = mention.getAttribute('entity')
        mentionId = mention.getAttribute('id')
        mentionIdToSpanId[mentionId] = 's' + str(nextMentionSpanId)
        mentionIdToMention[mentionId] = mention
        nextMentionSpanId += 1
        mention.setAttribute('oid', mentionId)
        mention.setAttribute('id', mentionIdToSpanId[mentionId])
        if entityId:
            entity = entities[entityId]
            speakerName = entity['name'] if 'name' in entity else entityId
            # Rename attributes
            mention.setAttribute('speaker', speakerName)

    quotes = dom.getElementsByTagName('QUOTE')
    # Look for embedded quotes
    if extractNestedQuotes:
        for quote in quotes:
            nestedQuote = addNestedQuotes(quote)
            if nestedQuote:
                quote.parentNode.replaceChild(nestedQuote, quote)
    # Go over quotes and match them to characters
    quotes = dom.getElementsByTagName('QUOTE')
    quoteIdToSpanId = {}
    nextQuoteSpanId = nextMentionSpanId
    speakerMentions = Set()
    speakers = Set()
    noSpeaker = 0
    nQuotes = 0
    for quote in quotes:
        nQuotes += 1
        speakerMentionId = quote.getAttribute('speaker')
        quoteId = quote.getAttribute('id')
        quoteSpanId = 's' + str(nextQuoteSpanId)
        quoteIdToSpanId[quoteId] = quoteSpanId
        nextQuoteSpanId += 1
        quote.setAttribute('oid', quoteId)
        quote.setAttribute('id', quoteIdToSpanId[quoteId])
        if speakerMentionId and speakerMentionId != 'none':
            speakerMentions.add(speakerMentionId)
            speakerId = mentionIdToEntityId.get(speakerMentionId)
            if speakerId:
                entity = entities[speakerId]
                speakerName =  entity['name'] if 'name' in entity else speakerId
                # Rename attributes
                #quote.setAttribute('speakerId', speakerId)
                quote.setAttribute('speaker', speakerName)
                quote.setAttribute('mention', speakerMentionId)
                if not mentionLevel == 'QUOTES':  # No need to set connection if no mentions will be output
                    quote.setAttribute('connection', mentionIdToSpanId[speakerMentionId])
                # Add connection to mention
                mention = mentionIdToMention[speakerMentionId]
                if not mentionLevel == 'QUOTES':  # No need to set connection if no mentions will be output
                    mconn = mention.getAttribute('connection')
                    if len(mconn) > 0:
                        mention.setAttribute('connection',  mconn + ',' + quoteSpanId)
                    else:
                        mention.setAttribute('connection', quoteSpanId)
            else:
                # Special case handling for speakers we added in this script
                if not speakerMentionId in ['James_McCarthy', 'Coroner', 'Juryman']:
                    print 'No speaker for ' + speakerMentionId
                speakerName = speakerMentionId
                quote.setAttribute('speaker', speakerName)
        else:
            noSpeaker += 1
            #print 'Unknown speaker for ' + quote.toxml('utf-8')
    print 'No speaker for ' + str(noSpeaker) + '/' + str(nQuotes) + ' quotes'

    # Trim based on mention level
    if mentionLevel == 'QUOTES': # only show quotes (remove mentions)
        mentions = dom.getElementsByTagName('MENTION')
        for mention in mentions:
            t = dom.createTextNode(get_all_text(mention))
            mention.parentNode.replaceChild(t, mention)
    elif mentionLevel == 'DIRECT': # only show mention that are linked as speakers
       mentions = dom.getElementsByTagName('MENTION')
       for mention in mentions:
           if mention.getAttribute('oid') not in speakerMentions:
               t = dom.createTextNode(get_all_text(mention))
               mention.parentNode.replaceChild(t, mention)
    # default 'ALL' (keep everything)

    # Convert tags to lowercase
    lowercaseTags(dom)

    # Output
    writeConverted(dom, outfilename, splitChapters, includeSectionTags)
    
    (temp, ext) = os.path.splitext(outfilename)
    (base, ext2) = os.path.splitext(temp)
    writeEntities(entitiesElement, base + ".entities" + ext)

def convertMentionLevels(infilename, outname, charactersFile, splitChapters, includeSectionTags, extractNestedQuotes):
    mentionLevels = ["ALL", "DIRECT", "QUOTES"]
    (outbase, outext) = os.path.splitext(outname)
    outext = outext or '.xml'
    for mentionLevel in mentionLevels:
        outfilename = outbase + '.' + mentionLevel.lower() + outext
        with open(infilename, 'r') as infile:
            convert(infile, outfilename, charactersFile,
                mentionLevel, splitChapters, includeSectionTags, extractNestedQuotes)


def main():
    # Argument processing
    parser = argparse.ArgumentParser(description='Convert CQSC XML')
    parser.add_argument('-c', '--characters', dest='charactersFile', help='characters file', action='store')
    parser.add_argument('-s', '--split', dest='splitChapters', help='split by chapter', action='store_true')
    parser.add_argument('-p', dest='includeSectionTags', help='paragraphs and headings', action='store_true')
    parser.add_argument('-n', dest='extractNestedQuotes', help='exract nested quotes', action='store_true')
    parser.add_argument('infile')
    parser.add_argument('outfile', nargs='?')
    args = parser.parse_args()
    outname = args.outfile or args.infile
    convertMentionLevels(args.infile, outname, args.charactersFile,
            args.splitChapters, args.includeSectionTags, args.extractNestedQuotes)

if __name__ == "__main__": main()