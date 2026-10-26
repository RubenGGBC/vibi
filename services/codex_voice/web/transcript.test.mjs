import test from 'node:test';
import assert from 'node:assert/strict';
import { TranscriptAssembler } from './transcript.mjs';

test('joins timed voice fragments into a single readable sentence', () => {
  const transcript = new TranscriptAssembler();
  const first = transcript.push({type:'output_transcript.added',item:{id:'a',text:' Hola,'}});
  const next = transcript.push({type:'output_transcript.added',item:{id:'b',text:' soy Vibi.'}});
  assert.equal(next.key,first.key);
  assert.equal(next.text,'Hola, soy Vibi.');
});
test('keeps user and assistant speech separate and ignores duplicate fragments', () => {
  const transcript = new TranscriptAssembler();
  const first = transcript.push({type:'input_transcript.added',item:{id:'a',text:'Hola'}});
  assert.equal(transcript.push({type:'input_transcript.added',item:{id:'a',text:'Hola'}}),null);
  const answer = transcript.push({type:'output_transcript.added',item:{id:'b',text:'Buenas'}});
  assert.notEqual(answer.key,first.key);
  assert.equal(answer.role,'assistant');
});
test('starts a fresh line after a completed turn', () => {
  const transcript = new TranscriptAssembler();
  const first = transcript.push({type:'output_transcript.added',item:{id:'a',text:'Hola'}});
  transcript.push({type:'turn.done'});
  const next = transcript.push({type:'output_transcript.added',item:{id:'b',text:'Adiós'}});
  assert.notEqual(next.key,first.key);
  assert.equal(next.text,'Adiós');
});
