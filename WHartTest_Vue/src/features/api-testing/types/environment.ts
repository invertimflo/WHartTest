import type { UserBrief } from './common';

export interface ApiClientCertificateBrief {
  id: number;
  name: string;
  cert_type: 'pem' | 'pkcs12';
  has_passphrase: boolean;
  is_active: boolean;
}

export interface ApiEnvironment {
  id: number;
  name: string;
  base_url: string;
  verify_ssl: boolean;
  description: string;
  project: number;
  parent: number | null;
  database_config: number | null;
  /** HTTPS 客户端证书（mTLS）引用，可为空 */
  client_certificate: number | null;
  client_certificate_info: ApiClientCertificateBrief | null;
  is_active: boolean;
  created_by: UserBrief | null;
  created_at: string;
  updated_at: string;
  [key: string]: any;
}

export type EnvironmentVariableType =
  | 'string'
  | 'integer'
  | 'float'
  | 'boolean'
  | 'json'
  | 'list'
  | 'dict';

export interface ApiEnvironmentVariable {
  id: number;
  environment: number;
  name: string;
  value: string;
  type: EnvironmentVariableType;
  description: string;
  is_sensitive: boolean;
  created_at: string;
  updated_at: string;
  [key: string]: any;
}

export interface ApiGlobalRequestHeader {
  id: number;
  name: string;
  value: string;
  description: string;
  is_enabled: boolean;
  project: number;
  created_by: UserBrief | null;
  created_at: string;
  updated_at: string;
  [key: string]: any;
}
