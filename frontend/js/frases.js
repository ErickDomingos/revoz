// Frases prontas por categoria: um lugar só, usado pelos modos Olhar e Digitar.
// Quem muda (login, editor em Ajustes) chama definirCategorias; quem mostra se inscreve com aoMudarFrases.
import { CATEGORIAS } from "./config.js";

const copiar = (cats) => cats.map((c) => ({ nome: c.nome, frases: [...c.frases] }));

let categorias = copiar(CATEGORIAS);
const ouvintes = [];

export const obterCategorias = () => copiar(categorias);
export const todasFrases = () => categorias.flatMap((c) => c.frases);
export const ehPadrao = () => JSON.stringify(categorias) === JSON.stringify(CATEGORIAS);

export function definirCategorias(novas) {
  const validas = (novas || []).filter((c) => c && c.nome && c.frases?.length);
  categorias = copiar(validas.length ? validas : CATEGORIAS);
  ouvintes.forEach((f) => f(obterCategorias()));
}

export function aoMudarFrases(funcao) {
  ouvintes.push(funcao);
  funcao(obterCategorias());
}
